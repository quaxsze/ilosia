import json
import subprocess
import tempfile
from pathlib import Path

from .exceptions import HelmInstallError, HelmUninstallError


class HelmClient:
    def install(self, *, release_name, chart_path, namespace, values):
        chart_path = Path(chart_path)
        if not chart_path.is_dir():
            raise HelmInstallError(f"Helm chart not found: {chart_path}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as values_file:
            json.dump(values, values_file)
            values_file.flush()
            command = [
                "helm",
                "upgrade",
                "--install",
                release_name,
                str(chart_path),
                "--namespace",
                namespace,
                "--create-namespace",
                "--values",
                values_file.name,
                "--wait",
                "--atomic",
                "--timeout",
                "5m",
            ]
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=330,
                )
            except (OSError, subprocess.SubprocessError) as error:
                detail = getattr(error, "stderr", None) or str(error)
                raise HelmInstallError(detail) from error

    def uninstall(self, *, release_name, namespace):
        command = [
            "helm",
            "uninstall",
            release_name,
            "--namespace",
            namespace,
            "--ignore-not-found",
            "--wait",
            "--timeout",
            "5m",
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=330,
            )
        except (OSError, subprocess.SubprocessError) as error:
            detail = getattr(error, "stderr", None) or str(error)
            raise HelmUninstallError(detail) from error
