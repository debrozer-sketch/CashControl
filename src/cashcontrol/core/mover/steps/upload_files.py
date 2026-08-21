"""
upload_files.py — Upload files to cash register via SCP.

Config format in scenario JSON:
    {
        "pos": ["file1.xml", "file2.jar", ...],
        "touch": ["file1.xml", "file3.sql", ...],
        "sco3": ["file1.xml", ...]
    }

Files are read from mover/files/ directory and uploaded to /home/tc/storage/ on the cash.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cashcontrol.core.mover.steps.base import BaseStep, ExecutionContext, StepResult
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_mover_files_dir

if TYPE_CHECKING:
    from cashcontrol.core.mover.scenario import StepDefinition

logger = get_logger()

REMOTE_UPLOAD_DIR = "/home/tc/storage"


class UploadFilesStep(BaseStep):
    """Upload files to cash register based on cash type."""

    async def execute(
        self,
        step_def: StepDefinition,
        ctx: ExecutionContext,
    ) -> StepResult:
        config = step_def.config
        cash_type = ctx.cash_type.lower()

        # Get file list for this cash type
        files_to_upload: list[str] = config.get(cash_type, [])
        if not files_to_upload:
            return StepResult(
                success=True,
                message=f"Нет файлов для типа '{cash_type}'",
            )

        local_dir = get_mover_files_dir()
        if not local_dir.exists():
            return StepResult(
                success=False,
                message=f"Папка с файлами не найдена: {local_dir}",
            )

        # Check all files exist locally before uploading
        missing: list[str] = []
        for filename in files_to_upload:
            local_path = local_dir / filename
            if not local_path.exists():
                missing.append(filename)

        if missing:
            return StepResult(
                success=False,
                message=f"Не найдены файлы: {', '.join(missing)}",
                details=[f"❌ {f}" for f in missing],
            )

        # Upload each file
        await ctx.log(f"Загрузка {len(files_to_upload)} файлов...")

        success_count = 0
        failed: list[str] = []
        result = StepResult(success=True, message="")

        for i, filename in enumerate(files_to_upload, 1):
            local_path = str(local_dir / filename)
            remote_path = f"{REMOTE_UPLOAD_DIR}/{filename}"

            await ctx.log(f"  [{i}/{len(files_to_upload)}] {filename}")

            try:
                await ctx.session.ssh.upload_file(local_path, remote_path)
                success_count += 1
                result.add_detail(f"✅ {filename}")
            except Exception as e:
                failed.append(f"{filename}: {e}")
                result.add_detail(f"❌ {filename}: {e}")
                logger.error(f"Upload failed {filename} to {ctx.session.host}: {e}")

        if failed:
            result.success = False
            result.message = (
                f"Загружено {success_count}/{len(files_to_upload)}, "
                f"ошибки: {len(failed)}"
            )
        else:
            result.message = f"Загружено {success_count} файлов"

        return result