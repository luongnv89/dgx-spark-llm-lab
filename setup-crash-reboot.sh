#!/usr/bin/env bash
# setup-crash-reboot.sh — enable automatic reboot on kernel crash
# Run with: sudo bash setup-crash-reboot.sh
set -euo pipefail

echo "=== Enabling automatic reboot on kernel crash ==="

# 1. Enable kernel panic auto-reboot (30s delay)
echo "[1/6] kernel.panic = 30"
sudo sysctl -w kernel.panic=30

# 2. Reboot on oops (non-fatal kernel errors)
echo "[2/6] kernel.panic_on_oops = 1"
sudo sysctl -w kernel.panic_on_oops=1

# 3. Reboot on RCU stall
echo "[3/6] kernel.panic_on_rcu_stall = 1"
sudo sysctl -w kernel.panic_on_rcu_stall=1

# 4. Reboot on hard lockup (NMI-triggered)
echo "[4/6] kernel.hardlockup_panic = 1"
sudo sysctl -w kernel.hardlockup_panic=1

# 5. Reboot on soft lockup (watchdog-triggered)
echo "[5/6] kernel.softlockup_panic = 1"
sudo sysctl -w kernel.softlockup_panic=1

# 6. Enable NMI watchdog
echo "[6/6] kernel.nmi_watchdog = 1"
sudo sysctl -w kernel.nmi_watchdog=1

# --- Make persistent ---
echo ""
echo "=== Making settings persistent across reboots ==="

sudo bash -c 'cat > /etc/sysctl.d/99-crash-reboot.conf << '\''EOF'\''
# Automatically reboot on kernel crash / panic / stall
# 30 seconds after panic before rebooting
kernel.panic = 30
# Reboot on oops (non-fatal kernel errors)
kernel.panic_on_oops = 1
# Reboot on RCU stall
kernel.panic_on_rcu_stall = 1
# Reboot on hard lockup (NMI-triggered)
kernel.hardlockup_panic = 1
# Reboot on soft lockup (watchdog-triggered)
kernel.softlockup_panic = 1
# Enable NMI watchdog for hard lockup detection
kernel.nmi_watchdog = 1
EOF'

echo "Written /etc/sysctl.d/99-crash-reboot.conf"
sudo sysctl -p /etc/sysctl.d/99-crash-reboot.conf

# --- Enable systemd CrashReboot ---
echo ""
echo "=== Enabling CrashReboot in systemd ==="
sudo sed -i 's/^#CrashReboot=no/CrashReboot=yes/' /etc/systemd/system.conf
sudo systemctl daemon-reload

echo ""
echo "=== Verification ==="
sudo sysctl kernel.panic kernel.panic_on_oops kernel.panic_on_rcu_stall \
    kernel.hardlockup_panic kernel.softlockup_panic kernel.nmi_watchdog
grep CrashReboot /etc/systemd/system.conf

echo ""
echo "=== Done! The machine will now auto-reboot on: ==="
echo "  - Kernel panic (after 30s)"
echo "  - Kernel oops (non-fatal errors)"
echo "  - RCU stall"
echo "  - Hard lockup (NMI watchdog)"
echo "  - Soft lockup (watchdog)"
echo "  - Any systemd service crash (CrashReboot=yes)"
