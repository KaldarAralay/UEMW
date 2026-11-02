"""Rebuild only the project-owned ambient cube; material shaders are unchanged."""
import unreal as u
probe=u.MWBuildLibrary.create_ambient_probe()
if probe is None or not u.EditorAssetLibrary.save_loaded_asset(probe,False):raise RuntimeError('Ambient probe could not be saved')
interior=u.MWBuildLibrary.create_interior_ambient_probe()
if interior is None or not u.EditorAssetLibrary.save_loaded_asset(interior,False):raise RuntimeError('Interior ambient probe could not be saved')
outdoor=u.MWBuildLibrary.create_outdoor_ambient_probe()
if outdoor is None or not u.EditorAssetLibrary.save_loaded_asset(outdoor,False):raise RuntimeError('Outdoor ambient probe could not be saved')
