"""
Mover step implementations.

Each step type has a corresponding class that inherits from BaseStep.
Steps are registered by type name and instantiated by the executor.
"""

from cashcontrol.core.mover.steps.base import BaseStep, StepResult
from cashcontrol.core.mover.steps.loymax import LoymaxStep
from cashcontrol.core.mover.steps.qrid import QridStep
from cashcontrol.core.mover.steps.run_commands import RunCommandsStep
from cashcontrol.core.mover.steps.set_com_port import SetComPortStep
from cashcontrol.core.mover.steps.upload_files import UploadFilesStep

# Registry: step type name → step class
STEP_REGISTRY: dict[str, type[BaseStep]] = {
    "upload_files": UploadFilesStep,
    "run_commands": RunCommandsStep,
    "loymax": LoymaxStep,
    "qrid": QridStep,
    "set_com_port": SetComPortStep,
}

__all__ = [
    "STEP_REGISTRY",
    "BaseStep",
    "LoymaxStep",
    "QridStep",
    "RunCommandsStep",
    "SetComPortStep",
    "StepResult",
    "UploadFilesStep",
]