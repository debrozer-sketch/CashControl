"""
Mover subsystem — deliver files, commands, and configuration to cash registers.

Provides scenario-based automation:
- Upload files (configs, plugins, media)
- Execute SSH commands
- Apply Loymax credentials from CSV
- Apply QRID from CSV (POS only)
- Set COM port for bank terminal (POS only)

Usage:
    from cashcontrol.core.mover.scenario import ScenarioManager
    from cashcontrol.core.mover.executor import MoverExecutor

    manager = ScenarioManager()
    scenario = manager.load("default")

    executor = MoverExecutor(session, scenario, params)
    async for progress in executor.run():
        print(progress)
"""