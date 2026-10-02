# [command]
# name        = Поправить_FITO
# description = Поправить FITO (макс. разрешение экрана)
# category    = user
# cash_types  = pos
# timeout     = 30

async def execute(session, **kwargs):
    import re
    cash_type = getattr(session, "cash_type", "") or ""
    if cash_type != "pos":
        return f"Command only for pos terminals (current type: {cash_type})"

    lines = []
    lines.append("Stopping cash...")
    try:
        r = await session.ssh.execute("cash stop", timeout=20)
    except Exception as e:
        return f"Failed to stop cash: {e}"

    import asyncio
    await asyncio.sleep(2)
    lines.append("Cash stopped")

    lines.append("Getting resolutions...")
    try:
        r = await session.ssh.execute("export DISPLAY=:0 && xrandr", timeout=10)
        xrandr_out = r.stdout or ""
    except Exception as e:
        return "\n".join(lines) + f"\nxrandr error: {e}"

    if not xrandr_out.strip():
        return "\n".join(lines) + "\nxrandr returned empty output"

    all_res = []
    current_output = None
    for line in xrandr_out.splitlines():
        m = re.match(r"^([a-zA-Z0-9_-]+)\s+connected", line)
        if m:
            current_output = m.group(1)
            continue
        if current_output and re.match(r"^\s+\d+x\d+", line):
            parts = line.strip().split()
            if len(parts) >= 2:
                resolution = parts[0]
                for part in parts[1:]:
                    try:
                        rate = float(part.rstrip("*+"))
                        if rate >= 50.0:
                            w, h = map(int, resolution.split("x"))
                            all_res.append({
                                "resolution": resolution,
                                "rate": rate,
                                "output": current_output,
                                "area": w * h,
                            })
                        break
                    except ValueError:
                        continue

    if not all_res:
        return "\n".join(lines) + "\nNo suitable resolution found"

    best = max(all_res, key=lambda x: x["area"])
    res = best["resolution"]
    rate = f"{best['rate']:.2f}"
    out = best["output"]

    lines.append(f"Monitor: {out}")
    lines.append(f"Resolutions found: {len(all_res)}")
    lines.append(f"Selected: {res} @ {rate} Hz")

    cmd = f"DISPLAY=:0 xrandr --output {out} --mode {res} --rate {rate}"
    lines.append("Applying resolution...")
    try:
        r = await session.ssh.execute(cmd, timeout=10)
        if r.success:
            lines.append(f"Resolution {res}@{rate}Hz applied")
        else:
            err = r.stderr.strip() if r.stderr else "no output"
            lines.append(f"Failed to apply resolution: {err}")
    except Exception as e:
        lines.append(f"Error applying resolution: {e}")

    lines.append("")
    lines.append("Resolution persists until reboot.")
    return "\n".join(lines)