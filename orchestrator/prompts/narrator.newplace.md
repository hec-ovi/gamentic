## NEW PLACE: furnish it THIS turn
The location is new and bare. Establish it now so it is whole:
- describe_scene (short, concrete) with a `background`: the place's deeper story in 2-3 sentences (what it is, what it was, why it matters) - you will be reminded of it every turn spent here. Then set_scene_status (its mood).
- add_exit every way onward you imply (at least one; the way back is added for you).
- place_item what is here: fixed=true for scenery seen but not carried (an altar, a lever), fixed=false for loose loot, hidden=true for what must be searched out (reveal_item when found).
- A companion coming along must be set_following BEFORE or as you move them, or they are left behind.

Example (reasoning and tool calls are NEVER printed as text): the player just entered the drain tunnel.
It CALLS the tools: describe_scene("A brick gullet, ankle-deep in black water.", background="These drains predate the city above; smugglers widened them in the famine years, and things have been left down here ever since."), set_scene_status("tense"), add_exit("a rusted ladder up", "pump room"), place_item("scene", "bloated satchel", hidden=true) - real tool calls, never written into the reply.
The reply is ONLY the prose: The dark swallows the sound of your steps...
