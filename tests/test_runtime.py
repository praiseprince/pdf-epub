from __future__ import annotations

from local_app.config import Settings
from local_app.runtime import DEFAULT_MLX_URL, MlxServerManager, TunnelManager, ocr_backend, runtime_payload, set_ocr_backend


def test_set_ocr_backend_toggles_runtime_settings(tmp_path):
    settings = Settings(LOCAL_DATA_DIR=tmp_path, LOCAL_PADDLE_VL_BACKEND="", LOCAL_PADDLE_VL_SERVER_URL="")

    assert ocr_backend(settings) == "cpu"

    assert set_ocr_backend(settings, "mlx") == "mlx"
    assert ocr_backend(settings) == "mlx"
    assert settings.local_start_mlx is True
    assert settings.local_paddle_vl_backend == "mlx-vlm-server"
    assert settings.local_paddle_vl_server_url == DEFAULT_MLX_URL

    assert set_ocr_backend(settings, "cpu") == "cpu"
    assert ocr_backend(settings) == "cpu"
    assert settings.local_start_mlx is False
    assert settings.local_paddle_vl_backend == ""
    assert settings.local_paddle_vl_server_url == ""


def test_runtime_payload_includes_managed_services(tmp_path):
    settings = Settings(LOCAL_DATA_DIR=tmp_path, LOCAL_PADDLE_VL_BACKEND="", LOCAL_PADDLE_VL_SERVER_URL="")
    tunnel = TunnelManager(local_url="http://127.0.0.1:8000")
    mlx_server = MlxServerManager(settings=settings)

    payload = runtime_payload(settings, tunnel, mlx_server)

    assert payload["ocr_backend"] == "cpu"
    assert payload["mlx_server_url"] == DEFAULT_MLX_URL
    assert payload["tunnel"] == {"running": False, "url": "", "logs": []}
