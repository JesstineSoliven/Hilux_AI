# Workflow: Driving Mode Management

**Version:** 1.0
**Objective:** Toggle driving mode on or off via voice command. Fully offline.

---

## Inputs Required
- `memory/session_state.json`
- No API key required

## Intents That Trigger This Workflow
- `"driving_mode_on"` — activate driving mode
- `"driving_mode_off"` — deactivate driving mode

---

## What Driving Mode Changes

| Setting | Normal Mode | Driving Mode |
|---------|-------------|--------------|
| Claude max tokens | 800 | 150 |
| System prompt | Standard | + "Keep to 1-2 sentences" constraint |
| Response style | Full, detailed | Direct, minimal |
| Reminder readout | Full list | Count + first item only |
| Emotional responses | Up to 3 sentences | 2 sentences max always |

---

## Execution Sequence: Enable

```
1. Call driving_mode_tool.enable_driving_mode()
   → Sets session_state.json {"driving_mode": true}
2. Speak: "Driving mode on. I'll keep my answers short and focused."
3. Log: INFO "Driving mode ENABLED"
```

## Execution Sequence: Disable

```
1. Call driving_mode_tool.disable_driving_mode()
   → Sets session_state.json {"driving_mode": false}
2. Speak: "Driving mode off. Full responses are back."
3. Log: INFO "Driving mode DISABLED"
```

---

## Expected Outputs
- Immediate verbal confirmation
- All subsequent responses conform to new mode
- State persisted to session_state.json (survives restarts)

## Failure Handling
- JSON write failure → log warning, mode still changes in memory for session
- Already in requested state → still confirm: "Driving mode is already on."

## Performance Constraints
- All operations offline, < 50ms
- Confirmation must be spoken before next interaction
