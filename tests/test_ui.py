from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

import pytest
from fastapi.testclient import TestClient

from product_studio.app import STATIC_DIR
from product_studio.balance import BalanceConfig

UI_LOGIC_PATH = STATIC_DIR / "ui_logic.js"


def _run_node_eval(expression: str) -> Any:
    script = (
        f"const ui = require({json.dumps(str(UI_LOGIC_PATH))});\n"
        f"const result = ({expression});\n"
        "process.stdout.write(JSON.stringify(result));\n"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Node evaluation failed (code {completed.returncode}): {completed.stderr}"
        )
    return json.loads(completed.stdout)


def _compute_toolbar_state(**overrides: Any) -> dict[str, Any]:
    payload = {
        "total": 0,
        "doneCount": 0,
        "pendingCount": 0,
        "runningCount": 0,
        "errorCount": 0,
        "isBatchRunning": False,
        "stopRequested": False,
        "generationDisabled": False,
        "apiConfigured": True,
        **overrides,
    }
    return _run_node_eval(f"ui.computeToolbarState({json.dumps(payload)})")


@pytest.mark.node
def test_toolbar_state_highlights_generate_when_pending_items_exist() -> None:
    state = _compute_toolbar_state(total=3, doneCount=1, pendingCount=2)
    assert state["runButton"]["variant"] == "primary"
    assert state["runButton"]["label"] == "开始批量生成 (2 张待处理)"
    assert not state["runButton"]["disabled"]
    assert state["exportButton"]["variant"] == "secondary"
    assert not state["exportButton"]["disabled"]
    assert not state["retryFailedVisible"]


@pytest.mark.node
def test_toolbar_state_switches_primary_highlight_to_export_when_all_done() -> None:
    state = _compute_toolbar_state(total=4, doneCount=4)
    assert state["runButton"]["variant"] == "secondary"
    assert state["runButton"]["label"] == "重新生成全部 (4 张)"
    assert not state["runButton"]["disabled"]
    assert state["exportButton"]["variant"] == "primary"
    assert not state["exportButton"]["disabled"]


@pytest.mark.node
def test_toolbar_state_running_and_stopping_labels() -> None:
    running = _compute_toolbar_state(
        total=5, doneCount=2, pendingCount=2, runningCount=1, isBatchRunning=True
    )
    assert running["runButton"]["variant"] == "danger"
    assert running["runButton"]["label"] == "停止剩余任务 (2/5)"
    assert not running["runButton"]["disabled"]
    assert running["exportButton"]["variant"] == "secondary"

    stopping = _compute_toolbar_state(
        total=5,
        doneCount=2,
        pendingCount=2,
        runningCount=1,
        isBatchRunning=True,
        stopRequested=True,
    )
    assert stopping["runButton"]["label"] == "正在停止..."


@pytest.mark.node
def test_toolbar_state_handles_single_item_running_without_batch_mode() -> None:
    mid_run = _compute_toolbar_state(total=2, doneCount=1, runningCount=1)
    assert mid_run["runButton"]["disabled"]
    assert mid_run["runButton"]["label"] == "生成中... (1 张)"
    assert mid_run["exportButton"]["variant"] == "secondary"

    only_running = _compute_toolbar_state(total=1, doneCount=0, runningCount=1)
    assert only_running["runButton"]["disabled"]
    assert only_running["runButton"]["label"] == "生成中... (1 张)"
    assert only_running["exportButton"]["disabled"]


@pytest.mark.node
def test_toolbar_state_disabled_generation_promotes_export_when_results_exist() -> None:
    state = _compute_toolbar_state(
        total=3, doneCount=2, pendingCount=1, generationDisabled=True
    )
    assert state["runButton"]["disabled"]
    assert state["runButton"]["label"] == "余额不足，已禁用生图"
    assert state["exportButton"]["variant"] == "primary"
    assert not state["exportButton"]["disabled"]


@pytest.mark.node
def test_prompt_modified_detection() -> None:
    preset_prompt = "Extract only the main product"
    assert not _run_node_eval(
        f"ui.isPromptModified({json.dumps(preset_prompt)}, {json.dumps(preset_prompt)})"
    )
    assert not _run_node_eval(
        f"ui.isPromptModified({json.dumps('  ' + preset_prompt + '  ')}, {json.dumps(preset_prompt)})"
    )
    assert _run_node_eval(
        f"ui.isPromptModified({json.dumps(preset_prompt + ' keep shadow')}, {json.dumps(preset_prompt)})"
    )


@pytest.mark.node
def test_advanced_settings_dirty_detection() -> None:
    defaults = {
        "model": "gpt-image-2.5-sunburst",
        "quality": "medium",
        "concurrency": "2",
        "exportSize": "1000x1000",
        "exportFormat": "png",
        "autoCrop": True,
        "maxEdge": True,
        "enhanceSmall": True,
    }
    assert not _run_node_eval(
        f"ui.hasCustomAdvancedSettings({json.dumps(defaults)}, {json.dumps(defaults)})"
    )
    changed = {**defaults, "quality": "high"}
    assert _run_node_eval(
        f"ui.hasCustomAdvancedSettings({json.dumps(changed)}, {json.dumps(defaults)})"
    )
    changed_flag = {**defaults, "autoCrop": False}
    assert _run_node_eval(
        f"ui.hasCustomAdvancedSettings({json.dumps(changed_flag)}, {json.dumps(defaults)})"
    )


@pytest.mark.node
def test_clear_queue_only_confirms_when_completed_items_exist() -> None:
    assert not _run_node_eval(
        'ui.shouldConfirmClearQueue([{status: "pending"}, {status: "error"}])'
    )
    assert _run_node_eval(
        'ui.shouldConfirmClearQueue([{status: "pending"}, {status: "done"}])'
    )


@pytest.mark.node
def test_result_meta_summary_shows_cost_and_omits_technical_noise() -> None:
    summary = _run_node_eval(
        """ui.formatResultSummary({
            output_size: "1000x1000",
            size_kb: 245.6,
            elapsed: 8.4,
            model: "gpt-image-2.5-sunburst",
            quality: "medium",
            cost_usd: 0.042,
            usage: { total_tokens: 1500 },
            preprocess: { orig_size: "1200x2600", processed_size: "1024x1024", actions: ["长截图裁取"] }
        })"""
    )
    assert "1000x1000" in summary
    assert "245.6 KB" in summary
    assert "8.4s" in summary
    assert "约 $0.042" in summary
    assert "tokens" not in summary.lower()
    assert "预处理" not in summary
    assert "gpt-image" not in summary


@pytest.mark.node
def test_batch_cost_estimation_and_preprocess_tags() -> None:
    est = _run_node_eval(
        'ui.estimateBatchCostUsd(5, "gpt-image-2.5-sunburst", "medium")'
    )
    assert est == pytest.approx(0.2, abs=1e-3)
    mini_est = _run_node_eval('ui.estimateBatchCostUsd(4, "gpt-image-1-mini", "low")')
    assert mini_est == pytest.approx(0.024, abs=1e-3)

    tags = _run_node_eval(
        'ui.formatPreprocessTags({ actions: ["长截图裁取上半区", "长边限 1024px 缩放", "小图轻度锐化"] })'
    )
    assert tags == ["已裁长截图", "已限边缩放", "小图锐化"]

    friendly = _run_node_eval(
        'ui.formatFriendlyError("API 返回错误 (429): rate limit", 429)'
    )
    assert "429" in friendly
    assert "并发" in friendly


@pytest.mark.node
def test_derive_export_filename_and_plan_batch_export_names() -> None:
    assert (
        _run_node_eval('ui.deriveExportFilename("a1b2c3d4e5f6_SKU_1_white.png")')
        == "SKU_1_white.png"
    )
    assert (
        _run_node_eval(
            'ui.deriveExportFilename({ filename: "111111111111_old_white.png", export_filename: "custom_white.png" })'
        )
        == "custom_white.png"
    )
    assert _run_node_eval('ui.deriveExportFilename("plain.png")') == "plain.png"

    planned = _run_node_eval(
        """ui.planBatchExportNames(
            [
                { id: 1, result: { filename: "aaaaaaaaaaaa_mug_white.png" } },
                { id: 2, result: { filename: "bbbbbbbbbbbb_MUG_white.png" } },
                { id: 3, result: { filename: "cccccccccccc_cup_white.jpg" } }
            ],
            ["mug_white.png", "mug_white_2.png"]
        ).map((entry) => ({ id: entry.item.id, exportName: entry.exportName }))"""
    )
    assert planned == [
        {"id": 1, "exportName": "mug_white_3.png"},
        {"id": 2, "exportName": "MUG_white_4.png"},
        {"id": 3, "exportName": "cup_white.jpg"},
    ]


@pytest.mark.node
def test_toolbar_state_prioritizes_folder_export_when_supported_and_falls_back_to_zip() -> (
    None
):
    assert _run_node_eval("ui.resolvePrimaryExportMode(0, true)") == "folder"
    assert _run_node_eval("ui.resolvePrimaryExportMode(0, false)") == "zip"
    assert _run_node_eval("ui.resolvePrimaryExportMode(1, true)") == "single"
    assert _run_node_eval("ui.resolvePrimaryExportMode(1, false)") == "single"
    assert _run_node_eval("ui.resolvePrimaryExportMode(3, true)") == "folder"
    assert _run_node_eval("ui.resolvePrimaryExportMode(3, false)") == "zip"

    empty_with_folder = _compute_toolbar_state(
        total=3, doneCount=0, pendingCount=3, supportsFolderExport=True
    )
    assert empty_with_folder["exportButton"]["mode"] == "folder"
    assert empty_with_folder["exportButton"]["label"] == "保存到文件夹"
    assert empty_with_folder["exportButton"]["disabled"]
    assert not empty_with_folder["exportSplitVisible"]
    assert empty_with_folder["exportSplitDisabled"]

    empty_without_folder = _compute_toolbar_state(
        total=3, doneCount=0, pendingCount=3, supportsFolderExport=False
    )
    assert empty_without_folder["exportButton"]["mode"] == "zip"
    assert empty_without_folder["exportButton"]["label"] == "打包下载 ZIP"
    assert empty_without_folder["exportButton"]["disabled"]
    assert not empty_without_folder["exportSplitVisible"]
    assert empty_without_folder["exportSplitDisabled"]

    single_done = _compute_toolbar_state(
        total=1, doneCount=1, supportsFolderExport=True
    )
    assert single_done["exportButton"]["mode"] == "single"
    assert single_done["exportButton"]["label"] == "下载图片 (1 张)"
    assert single_done["exportButton"]["variant"] == "primary"
    assert not single_done["exportButton"]["disabled"]
    assert not single_done["exportSplitVisible"]
    assert single_done["exportSplitDisabled"]

    multi_with_folder = _compute_toolbar_state(
        total=3, doneCount=2, pendingCount=1, supportsFolderExport=True
    )
    assert multi_with_folder["exportButton"]["mode"] == "folder"
    assert multi_with_folder["exportButton"]["label"] == "保存到文件夹 (2 张)"
    assert not multi_with_folder["exportButton"]["disabled"]
    assert multi_with_folder["exportSplitVisible"]
    assert not multi_with_folder["exportSplitDisabled"]

    multi_without_folder = _compute_toolbar_state(
        total=3, doneCount=3, supportsFolderExport=False
    )
    assert multi_without_folder["exportButton"]["mode"] == "zip"
    assert multi_without_folder["exportButton"]["label"] == "打包下载 ZIP (3 张)"
    assert not multi_without_folder["exportSplitVisible"]
    assert multi_without_folder["exportSplitDisabled"]

    exporting_while_running = _compute_toolbar_state(
        total=4,
        doneCount=2,
        pendingCount=1,
        runningCount=1,
        isBatchRunning=True,
        supportsFolderExport=True,
        isExporting=True,
    )
    assert not exporting_while_running["runButton"]["disabled"]
    assert exporting_while_running["exportButton"]["disabled"]
    assert exporting_while_running["exportSplitDisabled"]


@pytest.mark.node
def test_export_items_to_directory_avoids_overwrites_tracks_progress_and_tolerates_partial_failure() -> (
    None
):
    script = f"""
    const ui = require({json.dumps(str(UI_LOGIC_PATH))});
    async function main() {{
      const written = {{}};
      const removed = [];
      const progressEvents = [];
      const existing = ["mug_white.png"];
      const fakeDir = {{
        name: "AliExpressMain",
        async *keys() {{
          for (const name of existing) yield name;
        }},
        async getFileHandle(name, opts) {{
          if (!opts || !opts.create) throw new Error("expected create: true");
          return {{
            async createWritable() {{
              let chunks = [];
              return {{
                async write(data) {{
                  if (data === "write-fail") throw new Error("disk full");
                  chunks.push(data);
                }},
                async close() {{ written[name] = chunks.join(""); }},
                async abort() {{ chunks = []; }},
              }};
            }},
          }};
        }},
        async removeEntry(name) {{
          removed.push(name);
        }},
      }};

      const items = [
        {{ uid: "1", result: {{ filename: "aaaaaaaaaaaa_mug_white.png", url: "/api/outputs/1" }} }},
        {{ uid: "2", result: {{ filename: "bbbbbbbbbbbb_fail_white.png", url: "/api/outputs/2" }} }},
        {{ uid: "3", result: {{ filename: "cccccccccccc_mug_white.png", url: "/api/outputs/3" }} }},
        {{ uid: "4", result: {{ filename: "dddddddddddd_disk_white.png", url: "/api/outputs/4" }} }},
      ];

      const summary = await ui.exportItemsToDirectory(items, {{
        pickDirectory: async () => fakeDir,
        fetchBlob: async (item) => {{
          if (item.uid === "2") throw new Error("network error");
          if (item.uid === "4") return "write-fail";
          return "bytes-" + item.uid;
        }},
        onProgress: (evt) => progressEvents.push(evt),
      }});

      const abortSummary = await ui.exportItemsToDirectory(items, {{
        pickDirectory: async () => {{
          const err = new Error("user cancelled");
          err.name = "AbortError";
          throw err;
        }},
        fetchBlob: async () => "never",
      }});

      process.stdout.write(JSON.stringify({{ summary, written, removed, progressEvents, abortSummary }}));
    }}
    main().catch((err) => {{ console.error(err); process.exit(1); }});
    """
    completed = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    data = json.loads(completed.stdout)

    assert data["summary"]["cancelled"] is False
    assert data["summary"]["folderName"] == "AliExpressMain"
    assert data["summary"]["saved"] == 2
    assert data["summary"]["failed"] == 2
    assert data["summary"]["total"] == 4
    assert data["written"] == {
        "mug_white_2.png": "bytes-1",
        "mug_white_3.png": "bytes-3",
    }
    assert data["removed"] == ["disk_white.png"]
    assert [evt["current"] for evt in data["progressEvents"]] == [1, 2, 3, 4]
    assert data["abortSummary"]["cancelled"] is True
    assert data["abortSummary"]["saved"] == 0


class _IdOrderParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, str, dict[str, str | None]]] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        self.tags.append((tag, attr_map))
        elem_id = attr_map.get("id")
        if elem_id is not None:
            self.elements.append((elem_id, tag, attr_map))


@pytest.fixture
def ui_client(
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> TestClient:
    return make_client(None)


def _fetch_index_html(client: TestClient, auth_headers: dict[str, str]) -> str:
    response = client.get("/", headers=auth_headers)
    assert response.status_code == 200
    return response.text


def _parse_index_html(
    client: TestClient, auth_headers: dict[str, str]
) -> tuple[str, _IdOrderParser]:
    html = _fetch_index_html(client, auth_headers)
    parser = _IdOrderParser()
    parser.feed(html)
    return html, parser


def test_static_ui_logic_is_served(
    ui_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = ui_client.get("/static/ui_logic.js", headers=auth_headers)
    assert response.status_code == 200
    assert "computeToolbarState" in response.text


def test_svg_favicon_is_linked_and_served(
    ui_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _, parser = _parse_index_html(ui_client, auth_headers)
    icon_links = [
        attrs
        for tag, attrs in parser.tags
        if tag == "link" and attrs.get("rel") == "icon"
    ]
    assert icon_links == [
        {"rel": "icon", "type": "image/svg+xml", "href": "/static/favicon.svg"}
    ]
    brand_icons = [
        attrs
        for tag, attrs in parser.tags
        if tag == "img" and "brand-icon" in (attrs.get("class") or "").split()
    ]
    assert len(brand_icons) == 1
    assert brand_icons[0].get("src") == "/static/favicon.svg"

    for path in ("/static/favicon.svg", "/favicon.ico"):
        response = ui_client.get(path, headers=auth_headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in response.text


def test_single_column_layout_without_permanent_sidebar(
    ui_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _, parser = _parse_index_html(ui_client, auth_headers)
    sidebar_asides = [
        attrs
        for tag, attrs in parser.tags
        if tag == "aside" and "sidebar" in (attrs.get("class") or "").split()
    ]
    assert sidebar_asides == []


def test_workspace_vertical_order_and_toolbar_button_sequence(
    ui_client: TestClient, auth_headers: dict[str, str]
) -> None:
    html, parser = _parse_index_html(ui_client, auth_headers)
    ids = [elem_id for elem_id, _, _ in parser.elements]
    by_id = {elem_id: (tag, attrs) for elem_id, tag, attrs in parser.elements}

    for required_id in (
        "presetGrid",
        "promptInput",
        "promptModifiedBadge",
        "dropzone",
        "toolbar",
        "runBatchBtn",
        "retryFailedBtn",
        "exportSplitWrap",
        "batchExportBtn",
        "exportMenuBtn",
        "exportMenu",
        "zipExportMenuItem",
        "clearQueueBtn",
        "cardGrid",
        "historyZipBtn",
    ):
        assert required_id in by_id, f"Missing element #{required_id}"

    assert ids.index("presetGrid") < ids.index("promptInput")
    assert ids.index("promptInput") < ids.index("dropzone")
    assert ids.index("dropzone") < ids.index("toolbar")
    assert ids.index("toolbar") < ids.index("runBatchBtn")
    assert ids.index("runBatchBtn") < ids.index("retryFailedBtn")
    assert ids.index("retryFailedBtn") < ids.index("batchExportBtn")
    assert ids.index("batchExportBtn") < ids.index("exportMenuBtn")
    assert ids.index("exportMenuBtn") < ids.index("clearQueueBtn")
    assert ids.index("clearQueueBtn") < ids.index("cardGrid")
    assert "hidden" in by_id["exportMenuBtn"][1]
    assert "hidden" in by_id["exportMenu"][1]
    assert by_id["batchExportBtn"][1].get("onclick") == "triggerPrimaryExport()"
    assert by_id["zipExportMenuItem"][1].get("onclick") == "downloadAllZip()"
    assert by_id["historyZipBtn"][1].get("onclick") == "downloadHistoryZip()"
    assert "合并为单个压缩包，适合归档或转发" in html
    assert "保存到本地文件夹" not in html

    clear_classes = (by_id["clearQueueBtn"][1].get("class") or "").split()
    assert "btn-danger" not in clear_classes


def test_header_has_balance_hidden_gateway_and_advanced_drawer_controls(
    ui_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _, parser = _parse_index_html(ui_client, auth_headers)
    by_id = {elem_id: (tag, attrs) for elem_id, tag, attrs in parser.elements}

    assert "balanceStatus" in by_id
    assert "gatewayStatus" in by_id
    gateway_attrs = by_id["gatewayStatus"][1]
    style_value = (gateway_attrs.get("style") or "").replace(" ", "")
    assert "hidden" in gateway_attrs or "display:none" in style_value, (
        "gatewayStatus should be hidden by default until an error occurs"
    )

    for required_id in (
        "advancedSettingsBtn",
        "advancedDirtyDot",
        "advancedDrawer",
        "modelSelect",
        "qualitySelect",
        "concurrencySelect",
        "exportSizeSelect",
        "exportFormatSelect",
        "optAutoCrop",
        "optMaxEdge",
        "optEnhanceSmall",
        "resetAdvancedBtn",
    ):
        assert required_id in by_id, f"Missing element #{required_id}"


def test_removes_developer_noise_and_keeps_sticky_toolbar_css(
    ui_client: TestClient, auth_headers: dict[str, str]
) -> None:
    html = _fetch_index_html(ui_client, auth_headers)
    assert "Cloudflare AI Gateway" not in html
    assert "CF 网关已就绪" not in html
    assert "累计 Tokens" not in html
    assert "预处理：" not in html
    assert "position: sticky;" in html
    assert re.search(r"\.toolbar[\s\S]*?position:\s*sticky", html)


@pytest.mark.node
def test_inline_script_has_valid_javascript_syntax(
    ui_client: TestClient, auth_headers: dict[str, str]
) -> None:
    html = _fetch_index_html(ui_client, auth_headers)
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", html)
    assert len(scripts) >= 1
    for idx, script_body in enumerate(scripts):
        completed = subprocess.run(
            ["node", "--check"],
            input=script_body,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            f"Inline script #{idx} syntax error: {completed.stderr}"
        )


@pytest.mark.node
def test_static_javascript_files_have_valid_syntax() -> None:
    for filename in ("ui_logic.js", "studio.js"):
        script_path = STATIC_DIR / filename
        completed = subprocess.run(
            ["node", "--check", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, f"{filename} syntax error: {completed.stderr}"
