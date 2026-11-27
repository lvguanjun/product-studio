import base64
import binascii
import io
import json
import os
import re
import secrets
import time
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, cast

import httpx
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageEnhance, ImageOps
from pydantic import BaseModel

from product_studio.balance import (
    BalanceLedger,
    calculate_generation_cost,
    compute_key_fingerprint,
    resolve_record_cost,
)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
HEALTHZ_PATH = "/healthz"

DEFAULT_GATEWAY_URL = "https://api.openai.com/v1"

INTERNAL_ID_PREFIX_RE = re.compile(r"^[0-9a-f]{12}_(.+)$", re.IGNORECASE)


def derive_export_filename(stored_filename: str) -> str:
    safe_name = Path(stored_filename).name
    if not safe_name:
        return "product_white.png"
    matched = INTERNAL_ID_PREFIX_RE.match(safe_name)
    if matched:
        return matched.group(1)
    return safe_name


def allocate_unique_export_filename(
    desired_name: str,
    used_lower_names: set[str],
) -> str:
    safe_name = Path(desired_name).name or "product_white.png"
    if safe_name.lower() not in used_lower_names:
        used_lower_names.add(safe_name.lower())
        return safe_name

    parsed = Path(safe_name)
    stem = parsed.stem
    suffix = parsed.suffix
    counter = 2
    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if candidate.lower() not in used_lower_names:
            used_lower_names.add(candidate.lower())
            return candidate
        counter += 1

PRESETS = [
    {
        "id": "aliexpress_white",
        "name": "速卖通白底主图（推荐）",
        "tag": "去截图UI / 去鼠标 / 保小字",
        "description": "从实拍图或手机/网页截图中精准提取商品，换纯白底并保留包装文字与 Logo。",
        "prompt": (
            "Extract only the main product from this image and place it centered on a clean pure solid white (#FFFFFF) studio background "
            "for an AliExpress e-commerce main product photo (product occupies about 80% of the frame with balanced white margins). "
            "Completely remove any background surface, webpage text, watermarks, app UI elements, price tags, thumbnails, and mouse cursor arrows. "
            "Cleanly reconstruct any covered letters or edges. Keep the product's exact shape, proportions, colors, printed logo, and all text/numbers strictly accurate and sharp. "
            "Use clean even commercial studio lighting with a very subtle natural contact shadow beneath the product."
        ),
    },
    {
        "id": "handheld_cleanup",
        "name": "去手 / 杂乱实拍棚拍化",
        "tag": "去人手 / 摆正视角 / 提质感",
        "description": "适合手持实拍或桌面杂乱光线差的照片，去除人手与杂物并统一棚拍打光。",
        "prompt": (
            "Extract only the main product from this photo and render it as a crisp commercial studio product photograph on a pure solid white (#FFFFFF) background. "
            "Completely remove human hands, fingers, clutter, tabletops, cables, and shadows from the original background, seamlessly reconstructing any occluded parts of the product. "
            "Straighten slight camera tilt, balance exposure and white balance, preserve every real detail, logo, label, and texture faithfully, "
            "center the product occupying about 80% of the frame with a soft natural contact shadow directly underneath."
        ),
    },
    {
        "id": "strict_pure_white",
        "name": "极简绝对纯白（无阴影）",
        "tag": "RGB 255,255,255 / 严格过审",
        "description": "无底部阴影、边缘利落，适合对纯白底检测特别严格的类目。",
        "prompt": (
            "Isolate only the main product from this image onto a 100% pure flat solid white (#FFFFFF) background with no cast shadow, no gradient, and no floor line. "
            "Remove all UI overlays, watermarks, cursors, and background objects completely. "
            "Center the product neatly occupying about 80% of the square frame with crisp edges, accurate colors, and sharp faithful printed text and logos."
        ),
    },
    {
        "id": "premium_3c",
        "name": "3C / 包装盒高质感白底",
        "tag": "立体光影 / 锐利边缘",
        "description": "增强包装盒与数码配件的材质立体感与高光层次，适合高客单价主图。",
        "prompt": (
            "Transform the main product from this image into a high-end commercial studio hero product photo on a pure white (#FFFFFF) background. "
            "Remove all surrounding interface elements, text overlays, backgrounds, dust, glare, and cursor icons. "
            "Enhance surface cleanliness, crisp edges, and studio softbox lighting while keeping the product geometry, colors, stickers, logos, and all printed text 100% accurate and readable. "
            "Center the product cleanly at ~80% frame fill with a subtle refined studio grounding shadow."
        ),
    },
]

MODELS = [
    {
        "id": "gpt-image-2.5-sunburst",
        "label": "gpt-image-2.5-sunburst（默认推荐）",
        "supports_fidelity": False,
    },
    {
        "id": "gpt-image-2.5-flare",
        "label": "gpt-image-2.5-flare",
        "supports_fidelity": False,
    },
    {
        "id": "gpt-image-2",
        "label": "gpt-image-2",
        "supports_fidelity": False,
    },
    {
        "id": "gpt-image-1.5",
        "label": "gpt-image-1.5",
        "supports_fidelity": True,
    },
    {
        "id": "gpt-image-1-mini",
        "label": "gpt-image-1-mini（低成本）",
        "supports_fidelity": False,
    },
]

router = APIRouter()


def load_local_env() -> bool:
    return load_dotenv(Path.cwd() / ".env", override=False)


def resolve_output_dir(output_dir: Path | None = None) -> Path:
    if output_dir is not None:
        return Path(output_dir)
    env_dir = (os.getenv("OUTPUT_DIR") or "").strip()
    if env_dir:
        return Path(env_dir)
    return Path.cwd() / "outputs"


def get_output_dir(request: Request) -> Path:
    return cast(Path, request.app.state.output_dir)


def get_balance_ledger(request: Request) -> BalanceLedger:
    return cast(BalanceLedger, request.app.state.balance_ledger)


def get_access_key() -> str:
    return (os.getenv("ACCESS_KEY") or "").strip()


def verify_basic_auth(auth_header: str | None, expected_key: str) -> bool:
    if not auth_header:
        return False
    scheme, _, encoded = auth_header.partition(" ")
    if scheme.lower() != "basic" or not encoded.strip():
        return False
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    expected_bytes = expected_key.encode("utf-8")
    username_matches = secrets.compare_digest(username.encode("utf-8"), expected_bytes)
    password_matches = secrets.compare_digest(password.encode("utf-8"), expected_bytes)
    return bool(username_matches & password_matches)


async def basic_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.url.path == HEALTHZ_PATH and request.method in {"GET", "HEAD"}:
        return await call_next(request)
    expected_key = get_access_key()
    if not expected_key:
        return PlainTextResponse(
            "ACCESS_KEY is not configured.",
            status_code=503,
        )
    if not verify_basic_auth(request.headers.get("Authorization"), expected_key):
        return PlainTextResponse(
            "Unauthorized",
            status_code=401,
            headers={
                "WWW-Authenticate": 'Basic realm="Product Studio", charset="UTF-8"'
            },
        )
    return await call_next(request)


def get_api_config() -> tuple[str, str]:
    api_key = (os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    base_url = (os.getenv("OPENAI_BASE_URL") or DEFAULT_GATEWAY_URL).rstrip("/")
    return api_key, base_url


def preprocess_image(
    raw_bytes: bytes,
    auto_crop_screenshot: bool = True,
    max_input_edge: int = 1024,
    enhance_small: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    opened_image: Image.Image = Image.open(io.BytesIO(raw_bytes))
    transposed = ImageOps.exif_transpose(opened_image)
    image: Image.Image = transposed if transposed is not None else opened_image
    orig_width, orig_height = image.size
    actions: list[str] = []

    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        white_canvas = Image.new("RGB", image.size, (255, 255, 255))
        rgba_image = image.convert("RGBA")
        white_canvas.paste(rgba_image, mask=rgba_image.split()[3])
        image = white_canvas
        actions.append("透明底转白底")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size
    if auto_crop_screenshot and width > 0 and (height / width) >= 1.75:
        crop_top = int(height * 0.04)
        crop_bottom = int(height * 0.56)
        if crop_bottom > crop_top + 100:
            image = image.crop((0, crop_top, width, crop_bottom))
            actions.append(f"长截图裁取上半主图区 ({image.width}x{image.height})")

    width, height = image.size
    if max_input_edge > 0 and max(width, height) > max_input_edge:
        image.thumbnail((max_input_edge, max_input_edge), Image.Resampling.LANCZOS)
        actions.append(f"等比压缩至 {image.width}x{image.height} 省Token")
    elif enhance_small and max(width, height) < 650:
        image = ImageEnhance.Sharpness(image).enhance(1.2)
        image = ImageEnhance.Contrast(image).enhance(1.04)
        actions.append("小图轻度锐化增强")

    if not actions:
        actions.append("标准 RGB 直传")

    output_buffer = io.BytesIO()
    image.save(output_buffer, format="PNG", optimize=True)
    processed_bytes = output_buffer.getvalue()

    report = {
        "orig_size": f"{orig_width}x{orig_height}",
        "processed_size": f"{image.width}x{image.height}",
        "actions": actions,
        "input_kb": round(len(processed_bytes) / 1024, 1),
    }
    return processed_bytes, report


def postprocess_output(
    raw_bytes: bytes,
    export_size: str = "native",
    export_format: str = "png",
) -> tuple[bytes, str, str, str]:
    image: Image.Image = Image.open(io.BytesIO(raw_bytes))
    if image.mode != "RGB":
        white_canvas = Image.new("RGB", image.size, (255, 255, 255))
        rgba_image = image.convert("RGBA")
        white_canvas.paste(rgba_image, mask=rgba_image.split()[3])
        image = white_canvas

    if export_size in ("1000x1000", "800x800"):
        target_edge = int(export_size.split("x")[0])
        image = ImageOps.fit(
            image, (target_edge, target_edge), method=Image.Resampling.LANCZOS
        )

    final_dims = f"{image.width}x{image.height}"
    fmt = export_format.lower()
    buffer = io.BytesIO()
    if fmt in ("jpg", "jpeg"):
        image.save(buffer, format="JPEG", quality=94, optimize=True)
        return buffer.getvalue(), "jpg", "image/jpeg", final_dims
    if fmt == "webp":
        image.save(buffer, format="WEBP", quality=92, method=6)
        return buffer.getvalue(), "webp", "image/webp", final_dims
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), "png", "image/png", final_dims


@router.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get(HEALTHZ_PATH)
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/api/config")
async def get_config(
    ledger: Annotated[BalanceLedger, Depends(get_balance_ledger)],
) -> JSONResponse:
    api_key, base_url = get_api_config()
    balance = ledger.get_status(api_key)
    return JSONResponse(
        {
            "api_configured": bool(api_key),
            "gateway_url": base_url,
            "default_model": "gpt-image-2.5-sunburst",
            "default_quality": "medium",
            "models": MODELS,
            "presets": PRESETS,
            "balance": balance,
        }
    )


@router.get("/api/balance")
async def get_balance(
    ledger: Annotated[BalanceLedger, Depends(get_balance_ledger)],
) -> JSONResponse:
    api_key, _ = get_api_config()
    return JSONResponse(ledger.get_status(api_key))


@router.post("/api/generate")
async def generate_image(
    file: Annotated[UploadFile, File()],
    prompt: Annotated[str, Form()],
    output_dir: Annotated[Path, Depends(get_output_dir)],
    ledger: Annotated[BalanceLedger, Depends(get_balance_ledger)],
    model: Annotated[str, Form()] = "gpt-image-2.5-sunburst",
    quality: Annotated[str, Form()] = "medium",
    size: Annotated[str, Form()] = "1024x1024",
    export_size: Annotated[str, Form()] = "1000x1000",
    export_format: Annotated[str, Form()] = "png",
    auto_crop_screenshot: Annotated[bool, Form()] = True,
    max_input_edge: Annotated[int, Form()] = 1024,
    enhance_small: Annotated[bool, Form()] = True,
) -> JSONResponse:
    api_key, base_url = get_api_config()
    if not api_key:
        raise HTTPException(
            status_code=500, detail="未在 .env 中检测到 API_KEY 或 OPENAI_API_KEY"
        )

    current_balance = ledger.get_status(api_key)
    if current_balance["disabled"]:
        return JSONResponse(
            status_code=402,
            content={
                "code": "BALANCE_BELOW_THRESHOLD",
                "detail": current_balance["disabled_reason"],
                "balance": current_balance,
            },
        )

    raw_upload = await file.read()
    if not raw_upload:
        raise HTTPException(status_code=400, detail="上传的图片为空")

    started_at = time.time()
    try:
        processed_bytes, preprocess_report = preprocess_image(
            raw_upload,
            auto_crop_screenshot=auto_crop_screenshot,
            max_input_edge=max_input_edge,
            enhance_small=enhance_small,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"图片预处理失败: {exc}") from exc

    form_data: dict[str, str] = {
        "model": model,
        "prompt": prompt.strip(),
        "size": size,
        "quality": quality,
        "output_format": "png",
    }
    if model == "gpt-image-1.5":
        form_data["input_fidelity"] = "high"

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{base_url}/images/edits",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "ProductStudio/1.0",
                },
                data=form_data,
                files={"image": ("input.png", processed_bytes, "image/png")},
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="网关生成超时，请稍后重试") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"请求网关失败: {exc}") from exc

    if response.status_code != 200:
        error_detail = response.text[:500]
        try:
            err_json = response.json()
            if isinstance(err_json, dict) and "error" in err_json:
                err_obj = err_json["error"]
                error_detail = (
                    err_obj.get("message", error_detail)
                    if isinstance(err_obj, dict)
                    else str(err_obj)
                )
        except ValueError:
            pass
        raise HTTPException(
            status_code=response.status_code,
            detail=f"API 返回错误 ({response.status_code}): {error_detail}",
        )

    payload = response.json()
    data_list = payload.get("data") or []
    if not data_list or not data_list[0].get("b64_json"):
        raise HTTPException(status_code=502, detail="API 未返回图片数据")

    raw_generated = base64.b64decode(data_list[0]["b64_json"])
    final_bytes, ext, mime_type, final_dims = postprocess_output(
        raw_generated, export_size=export_size, export_format=export_format
    )

    item_id = uuid.uuid4().hex[:12]
    orig_stem = Path(file.filename or "product").stem[:40]
    safe_stem = (
        "".join(
            ch if (ch.isalnum() or ch in ("-", "_", ".")) else "_" for ch in orig_stem
        ).strip("_")
        or "product"
    )
    saved_name = f"{item_id}_{safe_stem}_white.{ext}"
    export_name = f"{safe_stem}_white.{ext}"
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_path = output_dir / saved_name
    saved_path.write_bytes(final_bytes)

    elapsed = round(time.time() - started_at, 2)
    usage = payload.get("usage") or {}
    cost_usd, cost_source = calculate_generation_cost(model, usage)
    created_at = int(time.time())
    key_fingerprint = compute_key_fingerprint(api_key)

    meta = {
        "id": item_id,
        "filename": saved_name,
        "export_filename": export_name,
        "orig_name": file.filename or "image.png",
        "url": f"/api/outputs/{saved_name}",
        "mime": mime_type,
        "size_kb": round(len(final_bytes) / 1024, 1),
        "output_size": final_dims,
        "model": model,
        "quality": quality,
        "elapsed": elapsed,
        "usage": usage,
        "cost_usd": cost_usd,
        "cost_source": cost_source,
        "key_fingerprint": key_fingerprint,
        "preprocess": preprocess_report,
        "created_at": created_at,
    }
    (output_dir / f"{item_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    updated_balance = ledger.record_charge(
        api_key,
        item_id=item_id,
        model=model,
        cost_usd=cost_usd,
        cost_source=cost_source,
        created_at=created_at,
    )
    return JSONResponse({**meta, "balance": updated_balance})


@router.get("/api/outputs/{filename}")
async def get_output_file(
    filename: str,
    output_dir: Annotated[Path, Depends(get_output_dir)],
) -> FileResponse:
    safe_name = Path(filename).name
    target = output_dir / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=derive_export_filename(safe_name))


@router.get("/api/history")
async def list_history(
    output_dir: Annotated[Path, Depends(get_output_dir)],
    limit: int = 40,
) -> JSONResponse:
    records: list[dict[str, Any]] = []
    for meta_file in output_dir.glob("*.json"):
        try:
            record = json.loads(meta_file.read_text(encoding="utf-8"))
            img_path = output_dir / Path(record.get("filename", "")).name
            if img_path.exists():
                if "cost_usd" not in record:
                    cost_usd, cost_source = resolve_record_cost(record)
                    record["cost_usd"] = cost_usd
                    record["cost_source"] = cost_source
                if not record.get("export_filename"):
                    record["export_filename"] = derive_export_filename(
                        str(record.get("filename", ""))
                    )
                records.append(record)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    records.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return JSONResponse({"items": records[:limit]})


class ZipRequest(BaseModel):
    filenames: list[str]


@router.post("/api/download-zip")
async def download_zip(
    body: ZipRequest,
    output_dir: Annotated[Path, Depends(get_output_dir)],
) -> StreamingResponse:
    if not body.filenames:
        raise HTTPException(status_code=400, detail="没有可打包的文件")

    zip_buffer = io.BytesIO()
    added_count = 0
    used_lower_names: set[str] = set()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for raw_name in body.filenames:
            safe_name = Path(raw_name).name
            file_path = output_dir / safe_name
            if file_path.exists() and file_path.is_file():
                export_name = allocate_unique_export_filename(
                    derive_export_filename(safe_name),
                    used_lower_names,
                )
                archive.write(file_path, arcname=export_name)
                added_count += 1

    if added_count == 0:
        raise HTTPException(status_code=404, detail="未找到对应的生成图片")

    zip_buffer.seek(0)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="aliexpress_white_bg_{stamp}.zip"'
        },
    )


def create_app(
    *,
    output_dir: Path | None = None,
    ledger: BalanceLedger | None = None,
    load_env: bool = True,
) -> FastAPI:
    if load_env:
        load_local_env()

    resolved_output_dir = resolve_output_dir(output_dir)
    resolved_ledger = (
        ledger if ledger is not None else BalanceLedger(resolved_output_dir)
    )

    app = FastAPI(title="速卖通白底主图批量工作室")
    app.state.output_dir = resolved_output_dir
    app.state.balance_ledger = resolved_ledger
    app.middleware("http")(basic_auth_middleware)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    return app
