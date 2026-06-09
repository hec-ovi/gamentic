## NEW PLACE: furnish it THIS turn
The location is new and bare. Establish it now so it is whole:
- describe_scene (short, concrete) and set_scene_status (its mood).
- add_exit every way onward you imply (at least one; the way back is added for you).
- place_item what is here: fixed=true for scenery seen but not carried (an altar, a lever), fixed=false for loose loot, hidden=true for what must be searched out (reveal_item when found).
- A companion coming along must be set_following BEFORE or as you move them, or they are left behind.

Example, player just entered the drain tunnel:
(think: new place. What IS this tunnel: look, mood, ways on, what lies here?)
Tools: describe_scene("A brick gullet, ankle-deep in black water."), set_scene_status("tense"), add_exit("a rusted ladder up", "pump room"), place_item("scene", "bloated satchel", hidden=true).
Prose: "The dark swallows the sound of your steps..."
