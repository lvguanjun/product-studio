# 现代 Python 项目最佳实践与本仓库现状对比研究

> 研究对象：`/home/ubuntu/study/product-studio`（FastAPI + Uvicorn + httpx + Pillow 批量白底商品图生成应用）  
> 研究日期：2026-11-27  
> 资料原则：所有事实与结论均回溯至一手官方文档、PEP 规范与第一方仓库，不引用二手博客。

---

## 1. 研究范围与一手资料来源总览

本研究围绕 `uv` + `pytest` + `ruff` + 静态类型检查（`ty` / `pyright` / `mypy`）以及 FastAPI 应用工程护栏展开，全部依据以下一手来源：

| 领域 | 一手来源 | 官方 URL |
|---|---|---|
| **uv 项目管理与运行** | Astral `uv` 官方文档（Projects、Layout、Dependencies、Config、Python Versions、FastAPI、GitHub Actions、pre-commit、CLI） | `https://docs.astral.sh/uv/guides/projects/`、`https://docs.astral.sh/uv/concepts/projects/layout/`、`https://docs.astral.sh/uv/concepts/projects/dependencies/`、`https://docs.astral.sh/uv/concepts/projects/config/`、`https://docs.astral.sh/uv/concepts/python-versions/`、`https://docs.astral.sh/uv/guides/integration/fastapi/`、`https://docs.astral.sh/uv/guides/integration/github/`、`https://docs.astral.sh/uv/guides/integration/pre-commit/`、`https://docs.astral.sh/uv/reference/cli/` |
| **Python 打包与规范** | PyPA Packaging User Guide、PEP 621、PEP 735 | `https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/`、`https://packaging.python.org/en/latest/specifications/pyproject-toml/`、`https://peps.python.org/pep-0621/`、`https://peps.python.org/pep-0735/` |
| **pytest 测试体系** | `pytest` 官方文档（Configuration、Fixtures、`monkeypatch`、`tmp_path`、`unittest` 兼容、Good Integration Practices） | `https://docs.pytest.org/en/stable/reference/customize.html`、`https://docs.pytest.org/en/stable/how-to/fixtures.html`、`https://docs.pytest.org/en/stable/how-to/monkeypatch.html`、`https://docs.pytest.org/en/stable/how-to/tmp_path.html`、`https://docs.pytest.org/en/stable/how-to/unittest.html`、`https://docs.pytest.org/en/stable/explanation/goodpractices.html` |
| **FastAPI / Pydantic 测试与类型** | FastAPI 官方文档（Testing、Async Tests、CLI）、Pydantic 官方文档（Mypy / Pyright） | `https://fastapi.tiangolo.com/tutorial/testing/`、`https://fastapi.tiangolo.com/advanced/async-tests/`、`https://fastapi.tiangolo.com/fastapi-cli/`、`https://docs.pydantic.dev/latest/integrations/mypy/`、`https://docs.pydantic.dev/latest/concepts/types/` |
| **ruff 检查与格式化** | Astral `ruff` 官方文档（Configuration、Linter、Formatter、Rules） | `https://docs.astral.sh/ruff/configuration/`、`https://docs.astral.sh/ruff/linter/`、`https://docs.astral.sh/ruff/formatter/`、`https://docs.astral.sh/ruff/rules/` |
| **静态类型检查** | Astral `ty`、Microsoft `pyright`、`mypy` 官方文档与仓库 | `https://docs.astral.sh/ty/`、`https://docs.astral.sh/ty/installation/`、`https://docs.astral.sh/ty/configuration/`、`https://github.com/astral-sh/ty`、`https://microsoft.github.io/pyright/`、`https://microsoft.github.io/pyright/configuration/`、`https://mypy.readthedocs.io/en/stable/config_file.html`、`https://mypy.readthedocs.io/en/stable/command_line.html` |
| **Git Hooks 护栏** | `pre-commit` 官方文档、`prek`（第一方 Rust 实现） | `https://pre-commit.com/`、`https://prek.j178.dev/`、`https://github.com/j178/prek` |

---

## 2. 现代 Python 项目最佳实践（基于一手官方文档）

### 2.1 `uv` 项目管理与运行方式

1. **标准项目三件套：`pyproject.toml` + `.python-version` + `uv.lock`**
   - `uv init` 默认生成 `pyproject.toml`、`.python-version`、`README.md` 等文件，并在首次执行 `uv lock` / `uv sync` / `uv run` 时生成跨平台的 `uv.lock`（[uv: Working on projects](https://docs.astral.sh/uv/guides/projects/)、[uv: Project layout](https://docs.astral.sh/uv/concepts/projects/layout/)）。
   - `uv.lock` 是人类可读但由 `uv` 自动管理的跨平台锁文件，官方明确要求**提交进版本控制**，且不应手动编辑（[uv: Project layout](https://docs.astral.sh/uv/concepts/projects/layout/)）。
   - `.python-version` 用于声明项目默认使用的 Python 版本（如 `3.12`），`uv` 在创建 `.venv` 和运行命令时自动读取该文件（优先级高于系统默认 Python），可在不缩窄 `requires-python` 兼容下限的同时锁定团队开发环境版本（[uv: Python versions](https://docs.astral.sh/uv/concepts/python-versions/)）。

2. **开发依赖管理：`[dependency-groups]`（PEP 735）取代旧式 `[project.optional-dependencies]` 滥用**
   - [PEP 735](https://peps.python.org/pep-0735/) 正式在 `pyproject.toml` 中引入 `[dependency-groups]`，专门用于存放**仅在本地开发、测试、Lint、文档构建时使用、不写入分发包元数据**的依赖（例如 `dev`、`test`、`lint`）。
   - `uv` 原生支持 PEP 735，通过 `uv add --dev <pkg>` 写入 `[dependency-groups]` 下的 `dev` 组，或用 `uv add --group <name> <pkg>` 写入自定义组（[uv: Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/)）。
   - `uv` 默认将 `dev` 组包含在 `default-groups` 中，因此执行 `uv sync` / `uv run` 时默认安装 `dev` 组；在生产部署或 Docker 构建中可通过 `uv sync --no-dev` 或 `--no-default-groups` 跳过开发依赖（[uv: Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/)）。
   - `uv` 已将早期的 `[tool.uv] dev-dependencies` 标记为不推荐使用（deprecated），官方建议迁移至标准 `[dependency-groups]`（[uv: Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/)）。

3. **应用 vs 库：`tool.uv.package` 的语义**
   - `uv` 区分**虚拟应用项目（application / non-package）**与**可打包分发的库/应用（package）**：如果 `pyproject.toml` 未定义 `[build-system]`，且也没有定义需要构建安装的字段（如 `[project.scripts]`），`uv` 默认将其视为非打包项目，**不会**把项目本身以 editable 方式安装进 `.venv`；反之，只要定义了 `[build-system]` 或 `[project.scripts]` 等入口点，`uv` 会触发打包构建，或者你可以显式设置 `[tool.uv] package = false` / `package = true` 来消除歧义（[uv: Configuring projects](https://docs.astral.sh/uv/concepts/projects/config/)）。
   - 对于需要被 `pytest`、`ruff`、`ty`、CLI 脚本稳定导入的项目，或者想要使用 `[project.scripts]` 暴露启动命令的项目，配置 `[build-system]`（如 `hatchling` 或 `uv_build`）并设为可打包项目，与保持 `package = false` 的纯脚本/应用模式，在导入路径和启动命令上有明显差异（详见第 2.2 节与第 4 节）。

4. **使用 `uv run` 与 `uv sync` 运行应用与测试**
   - `uv run <cmd>` 会在运行命令前自动确保锁文件与 `.venv` 同步，并在项目虚拟环境中执行命令（例如 `uv run pytest`、`uv run uvicorn app:app`、`uv run ruff check`）（[uv: Working on projects](https://docs.astral.sh/uv/guides/projects/)）。
   - FastAPI 官方集成指南中，`uv` 推荐通过 `uv run fastapi dev`（开发）或 `uv run fastapi run` / `uv run uvicorn ...`（生产）运行 FastAPI 应用（[uv: Using uv with FastAPI](https://docs.astral.sh/uv/guides/integration/fastapi/)、[FastAPI CLI](https://fastapi.tiangolo.com/fastapi-cli/)）。
   - CI 与生产部署场景下，官方建议使用 `uv sync --locked`（校验 `uv.lock` 与 `pyproject.toml` 一致，不一致则失败）或 `--frozen`（不更新锁文件直接按锁安装）（[uv: Using uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)、[uv CLI reference](https://docs.astral.sh/uv/reference/cli/)）。

---

### 2.2 目录结构与 `pyproject.toml` 配置（应用 vs 库）

1. **`pyproject.toml` 单一事实来源（PEP 621）**
   - [PEP 621](https://peps.python.org/pep-0621/) 和 [PyPA pyproject.toml specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/) 确立了 `[project]` 表作为项目核心元数据标准，同时将 `[tool.<name>]` 作为各工具（`uv`、`pytest`、`ruff`、`mypy`、`pyright`、`ty`）的统一配置落脚点，减少仓库根目录的碎片化配置文件（如 `.flake8`、`pytest.ini`、`setup.cfg`、`mypy.ini`）。

2. **`src/` 布局 vs `flat` 布局（官方权衡依据）**
   - 根据 [PyPA: `src` layout vs `flat` layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) 与 [pytest: Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)：
     - **`src/` 布局**（如 `src/product_studio/`）：强制测试导入的是**已安装进 `.venv` 的包**而不是工作目录中的裸文件，能避免“本地能跑、打包后漏文件或隐式依赖当前工作目录 `sys.path[0]`”的问题；PyPA 推荐用于**可分发库**或打算构建/安装成包的工程。配合 `src/` 布局时，通常需要配置 `[build-system]` 并将项目以 editable 方式安装（`uv` 在配置了 `[build-system]` 时自动完成）。
     - **`flat` 布局**（根目录直接放包或模块，如 `product_studio/` 或当前仓库的 `app.py` + `balance.py`）：结构简单、零打包仪式，适合**不作为第三方库发布的单仓库 Web 应用/内部工具**。但在 flat 布局下，若使用 `pytest` 运行 `tests/`，要注意 Python 导入路径问题——`pytest` 默认的 `prepend` 模式或 `pythonpath = ["."]` 可让 `tests/` 导入根目录模块，而把散落的顶层 `.py` 收拢进一个包目录（如 `product_studio/`）或 `src/product_studio/` 可以避免根目录命名冲突（例如 `app.py` 与其它工具或子模块撞名）并让静态类型检查与 `ruff` 配置更清晰。

---

### 2.3 `pytest` 测试体系与 FastAPI 应用测试实践

1. **在 `pyproject.toml` 中统一配置 `[tool.pytest.ini_options]`**
   - `pytest` 官方原生支持在 `pyproject.toml` 中使用 `[tool.pytest.ini_options]` 配置测试目录、命令行默认参数、Python 导入路径、自定义 `markers` 和告警过滤（[pytest: Configuration](https://docs.pytest.org/en/stable/reference/customize.html)）：
     - `testpaths = ["tests"]`：限制测试发现范围，避免扫描无关目录。
     - `pythonpath = ["."]`（flat 布局且未打包安装时常用，pytest 7+ 原生支持，[pytest: Configuration](https://docs.pytest.org/en/stable/reference/customize.html)）。
     - `addopts = ["-ra", "--strict-markers", "--strict-config"]`：输出非通过用例摘要，并在拼错 marker 或配置项时立即失败，防止静默误配置（[pytest: Configuration](https://docs.pytest.org/en/stable/reference/customize.html)）。
     - `markers = [...]`：显式注册如 `node` / `integration` 等标记，便于按需筛选（例如 `pytest -m "not node"`）。
   - 若未来希望使用严格类型化的原表配置，pytest 9.0 也引入了原生 TOML `[tool.pytest]` 表，但 `[tool.pytest.ini_options]` 仍是官方文档中兼容性最广的标准写法（[pytest: Configuration](https://docs.pytest.org/en/stable/reference/customize.html)）。

2. **渐进迁移：`pytest` 原生兼容 `unittest.TestCase`**
   - `pytest` 可以直接发现并运行现有的 `unittest.TestCase` 子类（无需一次性全部重写）（[pytest: How to use unittest-based tests with pytest](https://docs.pytest.org/en/stable/how-to/unittest.html)）。
   - 不过，官方文档指出 `unittest.TestCase` 子类无法直接使用 `pytest` 的函数参数式 fixture 注入与 `@pytest.mark.parametrize`（仅支持 `autouse` 类 fixture）（[pytest: unittest](https://docs.pytest.org/en/stable/how-to/unittest.html)）。因此新测试或重构测试推荐写为纯函数 + `assert` + fixtures。

3. **用内置 Fixtures 替代手工状态保存与清理**
   - `tmp_path`：为每个测试自动提供独立的 `pathlib.Path` 临时目录并自动管理生命周期，替代 `tempfile.TemporaryDirectory()` + `setUp`/`tearDown` 样板（[pytest: Temporary directories and files](https://docs.pytest.org/en/stable/how-to/tmp_path.html)）。
   - `monkeypatch`：提供 `monkeypatch.setenv()`、`monkeypatch.delenv()`、`monkeypatch.setattr()`，测试结束后自动还原环境变量和模块全局属性，替代手工备份/恢复 `os.environ` 和全局对象（[pytest: How to monkeypatch/mock modules and environments](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)）。
   - `conftest.py`：在 `tests/conftest.py` 中集中定义跨文件共享的 fixture（如鉴权 `auth_headers`、隔离的 `TestClient`、临时 `BalanceLedger`），避免多个测试文件重复搭建环境（[pytest: How to use fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)）。

4. **FastAPI 官方测试模式**
   - **同步集成测试**：FastAPI 官方推荐使用 `from fastapi.testclient import TestClient`（底层依赖 `httpx`，本项目已安装 `httpx>=0.28.0`）直接测试路由，不需要启动真实端口；若应用定义了 `lifespan` 启动/关闭事件，应使用 `with TestClient(app) as client:` 上下文管理器触发事件（[FastAPI: Testing](https://fastapi.tiangolo.com/tutorial/testing/)）。
   - **依赖覆盖（Dependency Overrides）**：FastAPI 官方鼓励把配置、账本/存储、鉴权或外部客户端封装为 `Depends(...)`，测试时通过 `app.dependency_overrides[dep] = fake_dep` 替换，而不是直接篡改模块级全局变量（如 `app_module.OUTPUT_DIR = ...`、`app_module.balance_ledger = ...`）（[FastAPI: Testing](https://fastapi.tiangolo.com/tutorial/testing/)）。
   - **异步端点测试**：当需要测试真实并发异步行为、后台协程或原生异步依赖时，FastAPI 官方推荐使用 `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` 配合 `anyio`（`pytest` + `anyio` 插件）或 `pytest-asyncio`（[FastAPI: Async Tests](https://fastapi.tiangolo.com/advanced/async-tests/)）。

---

### 2.4 `ruff` 代码检查与格式化

1. **一个工具替代传统 Lint + Format 工具链**
   - `ruff` 以 Rust 编写，提供 `ruff check`（Linter，可替代 `flake8`、`isort`、`pyupgrade`、`autoflake`、`bandit` 子集等）和 `ruff format`（Formatter，定位为 `black` 的直接替代品）（[Ruff: Linter](https://docs.astral.sh/ruff/linter/)、[Ruff: Formatter](https://docs.astral.sh/ruff/formatter/)）。

2. **`pyproject.toml` 中的推荐配置结构**
   - 在 `[tool.ruff]` 下配置公共选项：`line-length`（默认 88）、`target-version`（若未显式设置，Ruff 会自动从 `project.requires-python` 推断，例如 `>=3.11` 对应 `py311`）（[Ruff: Configuration](https://docs.astral.sh/ruff/configuration/)）。
   - 在 `[tool.ruff.lint]` 下使用 `extend-select`（推荐保留默认 `E4`/`E7`/`E9`/`F`，再按需增量开启规则集）而非盲目 `select = ["ALL"]`（官方明确警告 `ALL` 会在升级 Ruff 时引入大量新规则和冲突规则，[Ruff: Linter](https://docs.astral.sh/ruff/linter/)）：
     - 常见实用最小高质量组合：`I`（isort 导入排序）、`UP`（pyupgrade 现代 Python 3.11+ 语法）、`B`（flake8-bugbear 常见陷阱）、`SIM`（flake8-simplify）、`ASYNC`（异步常见坑，非常适合 FastAPI `async def` 路由）、`FAST`（FastAPI 专属规则，见 [Ruff Rules: FastAPI (`FAST`)](https://docs.astral.sh/ruff/rules/)）。
   - 如开启与 `ruff format` 存在冲突的格式类 Lint 规则（如 `E501` 某些场景、`COM812`、`ISC001` 等），官方有专门清单说明应交由 `ruff format` 处理并在 Lint 中忽略冲突项（[Ruff: Formatter - Conflicting lint rules](https://docs.astral.sh/ruff/formatter/)）。
   - 测试目录可在 `[tool.ruff.lint.per-file-ignores]` 中针对 `tests/**` 放宽特定规则（如 `S101` 允许 `assert`）。

3. **标准执行命令**
   - 开发期：`uv run ruff check --fix .` 与 `uv run ruff format .`
   - CI 校验期：`uv run ruff check .` 与 `uv run ruff format --check .`（[Ruff: Linter](https://docs.astral.sh/ruff/linter/)、[Ruff: Formatter](https://docs.astral.sh/ruff/formatter/)）。

---

### 2.5 静态类型检查选型对比（`ty` / `pyright` / `mypy`）

以下对比严格基于截至 2026 年的官方一手文档与仓库状态：

| 维度 | `ty`（Astral） | `pyright`（Microsoft） | `mypy`（Python 官方社区历史标准） |
|---|---|---|---|
| **官方定位与成熟度** | Astral 推出的极速 Rust 类型检查器与语言服务器。官方文档明确标注：**截至目前仍处于 beta / 预发布阶段（尚未发布 1.0 稳定版，面向生产使用需评估其诊断与规则仍在演进）**（[ty docs](https://docs.astral.sh/ty/)、[astral-sh/ty](https://github.com/astral-sh/ty)） | 成熟稳定、长期用于 VS Code Pylance 底层；官方明确为全功能静态类型检查器（[Pyright docs](https://microsoft.github.io/pyright/)） | 最成熟的老牌标准，生态插件最全（[Mypy docs](https://mypy.readthedocs.io/en/stable/)） |
| **速度与工具链一致性** | Rust 实现，极快；与 `uv`、`ruff` 同属 Astral 体系，体验高度一致，支持 `uv add --dev ty` 或 `uvx ty check`（[ty installation](https://docs.astral.sh/ty/installation/)） | Node/TypeScript 实现（Python 侧常通过 `pyright` PyPI 包装器或 `basedpyright` 调用），速度很快，但在纯 Python/CI 环境需注意 Node 运行时拉取或预装 | Python 实现（mypyc 编译），中小项目很快，大型项目增量缓存可接受，但冷启动慢于 Rust/Pyright |
| **配置方式（`pyproject.toml`）** | 原生 `[tool.ty.*]`（[ty configuration](https://docs.astral.sh/ty/configuration/)） | 原生 `[tool.pyright]`，支持 `typeCheckingMode = "standard" / "strict"`（[Pyright configuration](https://microsoft.github.io/pyright/configuration/)） | 原生 `[tool.mypy]`，支持 `strict = true` 或渐进开启 `check_untyped_defs` / `disallow_untyped_defs`（[Mypy config file](https://mypy.readthedocs.io/en/stable/config_file.html)） |
| **FastAPI / Pydantic 支持** | 持续快速补齐 Pydantic v2 / 标准 PEP 681 `dataclass_transform` 支持，但因其仍处 beta，边角泛型或部分第三方库 stub 行为可能随小版本变动（[ty docs](https://docs.astral.sh/ty/)） | 对 Pydantic v2 原生支持良好（Pydantic 官方文档注明 Pydantic v2 利用 PEP 681 与标准类型注解，Pyright **无需插件**即可开箱支持绝大多数能力，[Pydantic docs](https://docs.pydantic.dev/latest/concepts/types/)） | 成熟，且 Pydantic 官方提供一等 `pydantic.mypy` 插件用于补强 `BaseModel` 构造签名与校验器检查（[Pydantic Mypy integration](https://docs.pydantic.dev/latest/integrations/mypy/)） |
| **适合本仓库的场景** | 如果团队追求全 Astral 极简栈（`uv` + `ruff` + `ty`）、项目规模较小（目前仅 2 个业务模块）且能接受 beta 版本随升级微调规则，**最轻快** | 如果团队使用 VS Code / Cursor + Pylance，希望编辑器告警与 CI 100% 一致且不想维护插件，**一致性最好** | 如果偏好最稳妥、无 Node 依赖、CI 规则长期稳定且可启用 `pydantic.mypy` 插件，**最稳健** |

---

### 2.6 自动化护栏（命令入口、环境变量、CI / pre-commit）

1. **命令入口：`[project.scripts]` vs Shell 脚本（如 `start.sh`）**
   - `[project.scripts]`（[PEP 621](https://peps.python.org/pep-0621/)）允许定义如 `product-studio = "product_studio.cli:main"`，由 `uv sync` 自动安装到 `.venv/bin/`，可通过 `uv run product-studio` 跨平台执行，但**前提是项目以 package 模式构建安装**（即不能是 `package = false` 的纯非打包脚本项目，[uv: Configuring projects](https://docs.astral.sh/uv/concepts/projects/config/)）。
   - 如果项目只是单一服务的本地/服务器启动（且保持非打包模式），保留极简启动脚本或文档化的 `uv run uvicorn ...` / `uv run fastapi dev ...` 命令完全合法且零打包开销；甚至可以两者共存（代码内提供统一入口，脚本仅做环境变量默认值包装）。

2. **`.env` 环境变量加载：`uv run --env-file` vs `python-dotenv`**
   - `uv run` 原生支持 `--env-file .env`（以及环境变量 `UV_ENV_FILE`），可以在启动 Python 进程**之前**就把 `.env` 注入进程环境（[uv CLI reference](https://docs.astral.sh/uv/reference/cli/)）。
   - 在代码内调用 `python-dotenv` 的 `load_dotenv()` 适合直接用 `uvicorn app:app` 启动且不依赖 `--env-file` 参数的场景；但**在模块顶层导入时无条件执行 `load_dotenv(..., override=True)` 会带来测试污染风险**——每次 `import app` 都会把开发者本机 `.env` 里的真实 `API_KEY`、`ACCESS_KEY` 覆盖进 `os.environ`（甚至覆盖测试或 CI 显式传入的环境变量）。官方与工程实践推荐将配置读取延迟到应用工厂/配置对象/启动阶段，并默认 `override=False`（环境变量优先于 `.env` 文件）。

3. **CI 护栏（GitHub Actions 官方模板）**
   - `uv` 官方提供第一方 GitHub Action：`astral-sh/setup-uv`（支持版本固定与缓存）（[uv: Using uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)）。
   - 典型 CI 流水线（四道门禁）：
     1. `uv sync --locked --dev`（校验 `uv.lock` 未漂移并还原确定环境）
     2. `uv run ruff check .`（静态 Lint 检查）
     3. `uv run ruff format --check .`（格式一致性检查）
     4. `uv run <ty check | pyright | mypy .>`（静态类型检查）
     5. `uv run pytest`（自动化测试）

4. **本地 Git Hooks：`pre-commit` vs `prek`**
   - 经典方案是 `pre-commit`（[pre-commit.com](https://pre-commit.com/)），配合 `astral-sh/uv-pre-commit`（校验 `uv-lock`）和 `astral-sh/ruff-pre-commit`（[uv: Using uv with pre-commit](https://docs.astral.sh/uv/guides/integration/pre-commit/)）。
   - 新兴第一方 Rust 替代方案是 `prek`（[prek.j178.dev](https://prek.j178.dev/)、[j178/prek](https://github.com/j178/prek)）：与 `.pre-commit-config.yaml` 兼容、无需 Python 运行时管理 hook 环境且安装/运行显著更快；本地 hook 也可直接配置 `language: system` 调用 `uv run ruff check` / `uv run ruff format --check`，保证 hook 与 `uv.lock` 中的工具版本严格一致。

---

## 3. 当前仓库现状盘点与差距对照表

### 3.1 当前仓库客观快照（基于源码审计）

- **核心文件布局（flat 散落模块）**：
  - 根目录：`app.py`（496 行，FastAPI 应用、中间件、图像前后处理、全部路由）、`balance.py`（412 行，成本计算与本地 JSON 账本）、`pyproject.toml`（13 行）、`uv.lock`（已提交）、`start.sh`（6 行）、`.env.example`、`.gitignore`、`AGENTS.md`。
  - 前端静态资源：`static/index.html`、`static/studio.css`、`static/studio.js`、`static/ui_logic.js`。
  - 测试：`tests/test_balance.py`（272 行）、`tests/test_api_balance.py`（204 行）、`tests/test_ui.py`（346 行，含通过 `subprocess.run(["node", ...])` 验证 JS 逻辑与 HTML 内联脚本语法）。
- **依赖与环境**：
  - `pyproject.toml:5` 声明 `requires-python = ">=3.11"`，当前本地 `.venv` 实际为 `Python 3.12.3`，**没有 `.python-version` 文件**。
  - `pyproject.toml:6-13` 仅有 6 个运行时依赖：`fastapi`、`uvicorn[standard]`、`httpx`、`pillow`、`python-multipart`、`python-dotenv`。
  - `uv.lock` 中**不包含** `pytest`、`ruff`、`mypy`、`pyright`、`ty`、`pre-commit` 或 `prek`（通过扫描 `uv.lock` 确认）。
  - **没有任何 `[dependency-groups]`、`[build-system]`、`[tool.*]` 配置，也没有 `.github/workflows/` 或 `.pre-commit-config.yaml`**。

### 3.2 最佳实践 vs 当前仓库差距对照表

| 检查维度 | 现代最佳实践（一手来源） | 当前仓库现状（具体文件与行号） | 差距等级 |
|---|---|---|---|
| **Python 版本锁定** | 保留 `requires-python` 兼容下限，同时提交 `.python-version` 锁定团队默认版本（[uv Python versions](https://docs.astral.sh/uv/concepts/python-versions/)） | `pyproject.toml:5` 有 `requires-python = ">=3.11"`，但根目录缺少 `.python-version`（本地 `.venv` 为 3.12.3） | 中 |
| **开发依赖分组** | 使用 PEP 735 `[dependency-groups]` 的 `dev` 组管理测试/Lint/类型工具，锁入 `uv.lock`（[PEP 735](https://peps.python.org/pep-0735/)、[uv dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/)） | `pyproject.toml:1-13` 完全没有 `[dependency-groups]`；`uv.lock` 不含 `pytest` / `ruff` / 类型检查器 | **高** |
| **打包/非打包声明** | 明确选择 `tool.uv.package = false`（应用）或配置 `[build-system]`（包）以消除行为歧义（[uv config](https://docs.astral.sh/uv/concepts/projects/config/)） | `pyproject.toml` 未声明 `[build-system]` 也未显式声明 `[tool.uv] package = false`，处于隐式非打包状态 | 中 |
| **代码目录结构** | 应用可采用包目录（`product_studio/`）或 `src/product_studio/`，避免散落顶层 `.py` 与隐式导入风险（[PyPA src vs flat](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)） | `app.py`、`balance.py` 直接散落在仓库根目录；且 `app.py:34,40` 还读取了父目录 `ROOT_DIR = APP_DIR.parent` 下的 `../.env`（历史多目录遗留路径） | 中 |
| **测试运行器与配置** | 使用 `pytest` + `[tool.pytest.ini_options]`（`testpaths`、`addopts`、`markers`、`pythonpath`）（[pytest customize](https://docs.pytest.org/en/stable/reference/customize.html)） | 三个测试文件全基于 `unittest.TestCase`（`tests/test_balance.py:20`、`tests/test_api_balance.py:34`、`tests/test_ui.py:38`），无 `pytest` 依赖、无配置、无 `tests/conftest.py` | **高** |
| **测试隔离与 FastAPI 注入** | 使用 `tmp_path` + `monkeypatch` + `conftest.py` + FastAPI `Depends` / `dependency_overrides`（[pytest tmp_path](https://docs.pytest.org/en/stable/how-to/tmp_path.html)、[monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)、[FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)） | 手工 `tempfile.TemporaryDirectory()` + 手工复制还原 `os.environ`（`tests/test_api_balance.py:36-63`、`tests/test_ui.py:223-231`）；直接篡改模块全局状态 `app_module.OUTPUT_DIR` / `app_module.balance_ledger`（`tests/test_api_balance.py:51,67`） | **高** |
| **模块导入副作用（`.env` 与目录创建）** | 避免在 `import` 阶段执行文件 I/O 或 `override=True` 覆盖环境变量 | `app.py:37` 在导入时直接执行 `OUTPUT_DIR.mkdir(...)`；`app.py:40-41` 在导入时执行 `load_dotenv(ROOT_DIR / ".env")` 和 `load_dotenv(APP_DIR / ".env", override=True)`，会覆盖外部/测试环境变量，且可能误读仓库外部父目录 `.env` | **高** |
| **跨运行时测试边界（Node 依赖）** | 外部工具依赖的测试应有清晰 marker 或明确环境要求 | `tests/test_ui.py:25,331` 直接 `subprocess.run(["node", ...])`；若 CI 或某开发机未安装 Node，测试会直接报错且无法按 marker 拆分 | 中 |
| **Lint 与格式化（`ruff`）** | 在 `pyproject.toml` 配置 `[tool.ruff]`，用 `ruff check` + `ruff format` 统一风格与缺陷检查（[Ruff config](https://docs.astral.sh/ruff/configuration/)） | 完全未接入 `ruff`（例如 `tests/test_ui.py:1-6` 导入未排序、`app.py:155` 中间件缺少类型注解、`app.py:293-302` 使用旧式 `Form(...)` 默认值写法未受 `B008`/`FAST` 检查） | **高** |
| **静态类型检查** | 引入 `ty` / `pyright` / `mypy` 并写入 `pyproject.toml` 配置与检查命令 | 完全未接入静态类型检查；`balance.py` 类型标注较完整，但 `app.py` 存在多处未标注参数/返回值（如 `app.py:155 basic_auth_middleware`）和宽泛 `dict[str, Any]` | **高** |
| **异步 I/O 与 FastAPI 最佳实践** | 避免在 `async def` 路由中执行阻塞 I/O 或未复用的客户端，结合 `ruff` `ASYNC` / `FAST` 规则与 `lifespan` 管理客户端 | `app.py:292` 等 `async def` 路由中直接同步调用 Pillow 图像编解码、磁盘读写、`zipfile` 打包，且 `app.py:347` 每次请求新建 `httpx.AsyncClient`（注：此项偏代码质量改进，可与本次工程化升级分期处理） | 低-中（可选） |
| **`.gitignore` 覆盖工具缓存** | 忽略 `.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/`、`.coverage`、`htmlcov/` 等工具缓存 | `.gitignore:1-15` 仅忽略 `.env`、`.venv/`、`__pycache__/`、`outputs/`、`.DS_Store`，缺少测试/Lint/类型检查器缓存忽略规则 | 低 |
| **自动化护栏（CI & Hooks）** | GitHub Actions（`setup-uv` + `uv sync --locked` + `ruff` + typecheck + `pytest`）与可选 `pre-commit` / `prek`（[uv GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)） | 无 `.github/workflows/`，无 `.pre-commit-config.yaml`，无 `Makefile`/`justfile`/统一校验入口；`start.sh:6` 仅封装了 `uv run uvicorn app:app` | **高** |

### 3.3 值得特别指出的 4 个具体代码/配置细节

1. **`app.py:34,40-41` 的 `.env` 加载隐患**：
   ```python
   APP_DIR = Path(__file__).resolve().parent
   ROOT_DIR = APP_DIR.parent
   ...
   load_dotenv(ROOT_DIR / ".env")
   load_dotenv(APP_DIR / ".env", override=True)
   ```
   - 在当前独立仓库中，`ROOT_DIR` 指向 `/home/ubuntu/study`（仓库之外的父目录！），若父目录恰好存在 `.env` 会被意外加载。
   - `override=True` 会导致命令行显式传入的环境变量（如 `API_KEY=... uv run ...` 或 CI 注入的变量）在 `import app` 时被本地 `.env` 文件静默覆盖。

2. **`app.py:37-38` 的导入期副作用**：
   - 只要 `import app`，就会立即在仓库目录下创建 `outputs/` 并初始化全局 `balance_ledger = BalanceLedger(OUTPUT_DIR)`。这正是 `tests/test_api_balance.py:38-63` 不得不手工备份/篡改/恢复 `app_module.OUTPUT_DIR` 和 `app_module.balance_ledger` 的根因。

3. **`tests/test_api_balance.py` 与 `tests/test_ui.py` 的测试写法**：
   - 虽然已经在用 `fastapi.testclient.TestClient`（这是正确方向），但因缺少 `pytest`，测试文件充斥 `setUp`/`tearDown`、`self.assertEqual`、`tempfile.TemporaryDirectory()` 和手工 `os.environ` 备份恢复。

4. **`start.sh:6` 的启动方式**：
   - `exec uv run uvicorn app:app --host "$HOST" --port "$PORT"` 已经在使用 `uv run`，但没有 `--no-sync` 或 `--frozen` 区分（线上/本地策略未明确），也没提供开发热重载（`--reload` 或 `fastapi dev`）与标准校验脚本入口。

---

## 4. 待拍板的改造议题清单（供 `/grill-with-docs` 使用）

以下不是机械操作步骤，而是改造前真正需要用户权衡拍板的架构与工作流决策：

1. **目录结构与打包模式（flat 应用 vs `src/` 包布局）**
   - **选项 A（最小改动）**：保持根目录 flat 布局（甚至暂不挪动 `app.py`/`balance.py`），在 `pyproject.toml` 显式写 `[tool.uv] package = false` + `[tool.pytest.ini_options] pythonpath = ["."]`。优点：零路径变更、不破坏现有 `uvicorn app:app`；缺点：根目录随模块增长会变杂乱，也无法用 `[project.scripts]`。
   - **选项 B（包目录 / `src/` 布局）**：整理为 `src/product_studio/`（或根目录 `product_studio/` 包）+ `[build-system]`（如 `uv_build` 或 `hatchling`），拆分配置/路由/账本/图像处理模块，并可通过 `[project.scripts]` 暴露启动命令。优点：边界清晰、导入安全、易于扩展；缺点：改动现有导入路径与 `start.sh`。

2. **静态类型检查器选型（`ty` vs `pyright` vs `mypy`）**
   - **选项 A：`ty`** — 全 Astral 工具链（`uv` + `ruff` + `ty`），速度最快、零 Node 依赖，但官方仍标注为 beta / 预发布状态，升级时诊断可能有小幅变动。
   - **选项 B：`pyright`** — 成熟稳定、对 Pydantic v2 无需插件、与 VS Code / Cursor Pylance 诊断完全一致，但底层依赖 Node 运行时。
   - **选项 C：`mypy`** — 最稳健成熟、纯 Python、可用 `pydantic.mypy` 官方插件，但配置和速度相对略重。
   - **附带决策**：严格程度起点是「渐进模式（先检查现有签名 + 新代码要求标注）」还是「直接全量严格模式（`strict`）」？

3. **`pytest` 迁移深度（仅换 runner vs 重构为原生 pytest 风格）**
   - **选项 A（平滑过渡）**：引入 `pytest` 与 `[tool.pytest.ini_options]`，现有 `unittest.TestCase` 保持直接可跑，仅在新增测试时使用原生 `pytest` 函数与 fixtures。
   - **选项 B（彻底现代化）**：提取 `tests/conftest.py`，将现有 3 个测试文件改写为纯 `pytest` 函数 + `tmp_path` + `monkeypatch` + `parametrize`（并决定是否给依赖 `node` 的 UI 测试加上 `@pytest.mark.node` 标记）。

4. **是否顺带消除 `app.py` 的模块顶层副作用与全局状态（可测性重构边界）**
   - 改造范围是**仅限工程化外围配置**（`pyproject.toml`、工具链、测试 runner、CI），还是**同步修复** `app.py` 中阻碍测试与部署的根因问题：
     - 去掉 `ROOT_DIR = APP_DIR.parent` 读取外部 `.env` 及 `override=True`；
     - 用 FastAPI `Depends` / 应用状态或工厂函数替代模块级 `OUTPUT_DIR` / `balance_ledger` 全局可变状态，让测试走 `app.dependency_overrides` 而非 monkeypatch 全局变量？

5. **`ruff` 规则集严格度**
   - **选项 A（务实基线）**：默认规则（`E4`/`E7`/`E9`/`F`）+ `I`（导入排序）+ `UP`（py311+ 语法）+ `B`（bugbear）+ `SIM`（简化）+ `FAST`（FastAPI 专项），不强制 docstring（`D`）等高噪音规则。
   - **选项 B（更严格）**：额外启用 `ASYNC`、`S`（安全/bandit，测试放宽 `S101`）、`PT`（flake8-pytest-style）等规则。

6. **环境变量加载策略与启动入口**
   - `.env` 应由 `python-dotenv`（改为仅加载本仓库 `.env` 且 `override=False`）负责，还是迁移为 `uv run --env-file .env`（从而可评估是否还需要 `python-dotenv` 依赖）？
   - 启动入口是否保留 `start.sh`，还是统一为 `[project.scripts]` / `uv run fastapi dev` / `uv run fastapi run`（或 `Makefile` / `justfile` 任务入口）？

7. **自动化护栏落地范围（本地 Hooks + CI）**
   - 是否引入 `.github/workflows/ci.yml`（以及 CI 中是否需要安装 Node 以运行 `tests/test_ui.py`）？
   - 本地是否引入 Git pre-commit 护栏？若引入，选择 `prek` 还是传统 `pre-commit`，在 commit 阶段跑哪些检查（仅 `ruff` + `uv-lock`，还是连带类型检查）？
   - `.python-version` 锁定哪个具体次版本（例如与当前 `.venv` 一致的 `3.12`，还是 `3.13`）？
