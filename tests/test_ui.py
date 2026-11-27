import base64
import os
import re
import json
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module


REPO_ROOT = Path(__file__).resolve().parent.parent
UI_LOGIC_PATH = REPO_ROOT / "static" / "ui_logic.js"


def _run_node_eval(expression: str):
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


class TestUiLogic(unittest.TestCase):
    def _compute_toolbar_state(self, **overrides):
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

    def test_toolbar_state_highlights_generate_when_pending_items_exist(self):
        state = self._compute_toolbar_state(
            total=3, doneCount=1, pendingCount=2
        )
        self.assertEqual(state["runButton"]["variant"], "primary")
        self.assertEqual(state["runButton"]["label"], "开始批量生成 (2 张待处理)")
        self.assertFalse(state["runButton"]["disabled"])
        self.assertEqual(state["zipButton"]["variant"], "secondary")
        self.assertFalse(state["zipButton"]["disabled"])
        self.assertFalse(state["retryFailedVisible"])

    def test_toolbar_state_switches_primary_highlight_to_zip_when_all_done(self):
        state = self._compute_toolbar_state(total=4, doneCount=4)
        self.assertEqual(state["runButton"]["variant"], "secondary")
        self.assertEqual(state["runButton"]["label"], "重新生成全部 (4 张)")
        self.assertFalse(state["runButton"]["disabled"])
        self.assertEqual(state["zipButton"]["variant"], "primary")
        self.assertFalse(state["zipButton"]["disabled"])

    def test_toolbar_state_running_and_stopping_labels(self):
        running = self._compute_toolbar_state(
            total=5, doneCount=2, pendingCount=2, runningCount=1, isBatchRunning=True
        )
        self.assertEqual(running["runButton"]["variant"], "danger")
        self.assertEqual(running["runButton"]["label"], "停止剩余任务 (2/5)")
        self.assertFalse(running["runButton"]["disabled"])
        self.assertEqual(running["zipButton"]["variant"], "secondary")

        stopping = self._compute_toolbar_state(
            total=5,
            doneCount=2,
            pendingCount=2,
            runningCount=1,
            isBatchRunning=True,
            stopRequested=True,
        )
        self.assertEqual(stopping["runButton"]["label"], "正在停止...")

    def test_toolbar_state_handles_single_item_running_without_batch_mode(self):
        mid_run = self._compute_toolbar_state(total=2, doneCount=1, runningCount=1)
        self.assertTrue(mid_run["runButton"]["disabled"])
        self.assertEqual(mid_run["runButton"]["label"], "生成中... (1 张)")
        self.assertEqual(mid_run["zipButton"]["variant"], "secondary")

        only_running = self._compute_toolbar_state(total=1, doneCount=0, runningCount=1)
        self.assertTrue(only_running["runButton"]["disabled"])
        self.assertEqual(only_running["runButton"]["label"], "生成中... (1 张)")
        self.assertTrue(only_running["zipButton"]["disabled"])

    def test_toolbar_state_disabled_generation_promotes_zip_when_results_exist(self):
        state = self._compute_toolbar_state(
            total=3, doneCount=2, pendingCount=1, generationDisabled=True
        )
        self.assertTrue(state["runButton"]["disabled"])
        self.assertEqual(state["runButton"]["label"], "余额不足，已禁用生图")
        self.assertEqual(state["zipButton"]["variant"], "primary")
        self.assertFalse(state["zipButton"]["disabled"])

    def test_prompt_modified_detection(self):
        preset_prompt = "Extract only the main product"
        self.assertFalse(
            _run_node_eval(
                f"ui.isPromptModified({json.dumps(preset_prompt)}, {json.dumps(preset_prompt)})"
            )
        )
        self.assertFalse(
            _run_node_eval(
                f"ui.isPromptModified({json.dumps('  ' + preset_prompt + '  ')}, {json.dumps(preset_prompt)})"
            )
        )
        self.assertTrue(
            _run_node_eval(
                f"ui.isPromptModified({json.dumps(preset_prompt + ' keep shadow')}, {json.dumps(preset_prompt)})"
            )
        )

    def test_advanced_settings_dirty_detection(self):
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
        self.assertFalse(
            _run_node_eval(
                f"ui.hasCustomAdvancedSettings({json.dumps(defaults)}, {json.dumps(defaults)})"
            )
        )
        changed = {**defaults, "quality": "high"}
        self.assertTrue(
            _run_node_eval(
                f"ui.hasCustomAdvancedSettings({json.dumps(changed)}, {json.dumps(defaults)})"
            )
        )
        changed_flag = {**defaults, "autoCrop": False}
        self.assertTrue(
            _run_node_eval(
                f"ui.hasCustomAdvancedSettings({json.dumps(changed_flag)}, {json.dumps(defaults)})"
            )
        )

    def test_clear_queue_only_confirms_when_completed_items_exist(self):
        self.assertFalse(
            _run_node_eval(
                'ui.shouldConfirmClearQueue([{status: "pending"}, {status: "error"}])'
            )
        )
        self.assertTrue(
            _run_node_eval(
                'ui.shouldConfirmClearQueue([{status: "pending"}, {status: "done"}])'
            )
        )

    def test_result_meta_summary_shows_cost_and_omits_technical_noise(self):
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
        self.assertIn("1000x1000", summary)
        self.assertIn("245.6 KB", summary)
        self.assertIn("8.4s", summary)
        self.assertIn("约 $0.042", summary)
        self.assertNotIn("tokens", summary.lower())
        self.assertNotIn("预处理", summary)
        self.assertNotIn("gpt-image", summary)

    def test_batch_cost_estimation_and_preprocess_tags(self):
        est = _run_node_eval('ui.estimateBatchCostUsd(5, "gpt-image-2.5-sunburst", "medium")')
        self.assertAlmostEqual(est, 0.2, places=3)
        mini_est = _run_node_eval('ui.estimateBatchCostUsd(4, "gpt-image-1-mini", "low")')
        self.assertAlmostEqual(mini_est, 0.024, places=3)

        tags = _run_node_eval(
            'ui.formatPreprocessTags({ actions: ["长截图裁取上半区", "长边限 1024px 缩放", "小图轻度锐化"] })'
        )
        self.assertEqual(tags, ["已裁长截图", "已限边缩放", "小图锐化"])

        friendly = _run_node_eval('ui.formatFriendlyError("API 返回错误 (429): rate limit", 429)')
        self.assertIn("429", friendly)
        self.assertIn("并发", friendly)


class _IdOrderParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        self.tags.append((tag, attr_map))
        if "id" in attr_map:
            self.elements.append((attr_map["id"], tag, attr_map))


class TestIndexPageStructure(unittest.TestCase):
    def setUp(self):
        self.orig_env = dict(os.environ)
        os.environ["ACCESS_KEY"] = "test-access"
        self.client = TestClient(app_module.app)
        token = base64.b64encode(b"test-access:test-access").decode("ascii")
        self.auth_headers = {"Authorization": f"Basic {token}"}

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def _fetch_index_html(self) -> str:
        response = self.client.get("/", headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        return response.text

    def _parse_index_html(self) -> tuple[str, _IdOrderParser]:
        html = self._fetch_index_html()
        parser = _IdOrderParser()
        parser.feed(html)
        return html, parser

    def test_static_ui_logic_is_served(self):
        response = self.client.get("/static/ui_logic.js", headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("computeToolbarState", response.text)

    def test_single_column_layout_without_permanent_sidebar(self):
        _, parser = self._parse_index_html()
        sidebar_asides = [
            attrs
            for tag, attrs in parser.tags
            if tag == "aside" and "sidebar" in attrs.get("class", "").split()
        ]
        self.assertEqual(sidebar_asides, [])

    def test_workspace_vertical_order_and_toolbar_button_sequence(self):
        _, parser = self._parse_index_html()
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
            "zipBtn",
            "clearQueueBtn",
            "cardGrid",
        ):
            self.assertIn(required_id, by_id, f"Missing element #{required_id}")

        self.assertLess(ids.index("presetGrid"), ids.index("promptInput"))
        self.assertLess(ids.index("promptInput"), ids.index("dropzone"))
        self.assertLess(ids.index("dropzone"), ids.index("toolbar"))
        self.assertLess(ids.index("toolbar"), ids.index("runBatchBtn"))
        self.assertLess(ids.index("runBatchBtn"), ids.index("retryFailedBtn"))
        self.assertLess(ids.index("retryFailedBtn"), ids.index("zipBtn"))
        self.assertLess(ids.index("zipBtn"), ids.index("clearQueueBtn"))
        self.assertLess(ids.index("clearQueueBtn"), ids.index("cardGrid"))

        clear_classes = by_id["clearQueueBtn"][1].get("class", "").split()
        self.assertNotIn("btn-danger", clear_classes)

    def test_header_has_balance_hidden_gateway_and_advanced_drawer_controls(self):
        _, parser = self._parse_index_html()
        by_id = {elem_id: (tag, attrs) for elem_id, tag, attrs in parser.elements}

        self.assertIn("balanceStatus", by_id)
        self.assertIn("gatewayStatus", by_id)
        gateway_attrs = by_id["gatewayStatus"][1]
        self.assertTrue(
            "hidden" in gateway_attrs or "display:none" in gateway_attrs.get("style", "").replace(" ", ""),
            "gatewayStatus should be hidden by default until an error occurs",
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
            self.assertIn(required_id, by_id, f"Missing element #{required_id}")

    def test_removes_developer_noise_and_keeps_sticky_toolbar_css(self):
        html = self._fetch_index_html()
        self.assertNotIn("Cloudflare AI Gateway", html)
        self.assertNotIn("CF 网关已就绪", html)
        self.assertNotIn("累计 Tokens", html)
        self.assertNotIn("预处理：", html)
        self.assertIn("position: sticky;", html)
        self.assertRegex(html, r"\.toolbar[\s\S]*?position:\s*sticky")

    def test_inline_script_has_valid_javascript_syntax(self):
        html = self._fetch_index_html()
        scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", html)
        self.assertGreaterEqual(len(scripts), 1)
        for idx, script_body in enumerate(scripts):
            completed = subprocess.run(
                ["node", "--check"],
                input=script_body,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"Inline script #{idx} syntax error: {completed.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
