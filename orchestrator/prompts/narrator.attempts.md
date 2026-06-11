THE PLAYER ATTEMPTS, IN ORDER (adjudicate each one):
{{attempts}}

Accept an attempt by making it real with the matching tool (give_item for a handover, apply_damage for an attack), adjusting the amount if the fiction demands. Veto an attempt only when the world genuinely resists it: call reject_attempt(attempt, reason) with a short in-world reason the player will read. Anything you neither apply nor veto simply happens as attempted. A vetoed attempt may make later attempts moot; judge each on its own.

Example, attempts "1. give coin pouch to Mara" and "2. attack Bron (5 damage)": accept the first with give_item("coin pouch", "Mara"); veto the second with reject_attempt(2, "The crowd surges between you; your swing finds only air."). A veto reason is the WORLD resisting, never a character acting or speaking - their reactions are theirs to play (cue_character them instead).
