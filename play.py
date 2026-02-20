"""ARC-AGI-3 Starter Script - explore and play games."""

import arc_agi
from arcengine import GameAction

# Initialize the Arcade (offline mode - no API key needed)
arc = arc_agi.Arcade()

# List all available local environments
print("=== Available Environments ===")
envs = arc.get_environments()
for env_info in envs:
    print(f"  {env_info.game_id:20s}  {env_info.title}")

print(f"\nTotal: {len(envs)} environments")

# Play a sample game
print("\n=== Playing 'ls20' ===")
env = arc.make("ls20", render_mode="terminal")

for i in range(10):
    print(f"\n--- Step {i+1} ---")
    env.step(GameAction.ACTION1)

print("\n=== Scorecard ===")
print(arc.get_scorecard())
