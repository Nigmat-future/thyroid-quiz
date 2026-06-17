from __future__ import annotations

import subprocess
import shutil
import textwrap
from pathlib import Path

import pytest


def test_preload_next_question_image_requests_only_the_next_image(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the browser image preload module")

    module_url = (Path(__file__).parents[1] / "web" / "js" / "image_preload.js").as_uri()
    script = tmp_path / "preload_test.mjs"
    script.write_text(
        textwrap.dedent(
            f"""
            import assert from "node:assert/strict";
            import {{
              clearImagePreloadCache,
              getPreloadedImageUrls,
              preloadNextQuestionImage,
            }} from {module_url!r};

            const loaded = [];
            class FakeImage {{
              set decoding(value) {{
                this._decoding = value;
              }}
              set src(value) {{
                loaded.push({{ src: value, decoding: this._decoding }});
              }}
            }}

            const makeImage = () => new FakeImage();
            const questions = [
              {{ image_url: "/storage/images/a.jpg" }},
              {{ image_url: "/storage/images/b.jpg" }},
              {{ image_url: "/storage/images/c.jpg" }},
            ];

            clearImagePreloadCache();

            assert.equal(preloadNextQuestionImage(questions, 0, makeImage), true);
            assert.deepEqual(loaded, [
              {{ src: "/storage/images/b.jpg", decoding: "async" }},
            ]);

            assert.equal(preloadNextQuestionImage(questions, 0, makeImage), false);
            assert.deepEqual(loaded.map((item) => item.src), ["/storage/images/b.jpg"]);

            assert.equal(preloadNextQuestionImage(questions, 1, makeImage), true);
            assert.deepEqual(getPreloadedImageUrls(), [
              "/storage/images/b.jpg",
              "/storage/images/c.jpg",
            ]);

            assert.equal(preloadNextQuestionImage(questions, 2, makeImage), false);
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [node, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
