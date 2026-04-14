### v1.2.4.0_PreRelease

* NEW: Monster improvements and AI
* Improved console with monster debugging
* Added second weapon type (shotgun)
* Improved property editor flags, pickup types
* Resized/tidied/replaced some sprites and backported them to _1.2.0.0_stable_
* Named brushes can be triggered by I/O system (show/hide, change colour, non-solid)<br>
_Hidden brushes have **zero** render calls_

---------------

### v1.2.0.0_stable  |    MILESTONE 1

* NEW: Monster entity (Very basic, no AI - work in progress)
* NEW: Logic Graph Editor (**CTRL-L**) for visual scripting
* NEW: Logic Wizard (**CTRL-SHIFT-W**) To create quick logic (25 examples)
* FIXED YZ view dragging behaviour (was upside down!)
* FIXED frame pacing race condition (was causing flickering)
* Updated property editor layout
* Improved terrain editor: heightmaps, mouse-sculpting
* Entities now use internal UUIDs — I/O connections survive renames
* Property types preserved in save files (no more stringifying numbers/bools)
* Map format bumped to v3 (fully backwards compatible with v2/v1)
* Performance optimisations in logic_thread and renderer

---------------

### v1.1.0.0

* New `levelchange` entity
* Improved error handling
* Added renderer-related console commands
* Refactored level loading system - utilizes signals for safer state transitions
* Partial implementation of Monster entity
* Improvements to I/O system robustness
* FIXED?: Logic gates ([3](https://github.com/ViciousSquid/Fio/issues/3))

---------------


### v1.0.17.0

* Implemented explicit mixed-precision shader qualifiers: `highp` for vertex positions and `mediump` for lighting/colour calculations.
* Extended console_commands.py
* Improved console with `help` command

---------------


### v1.0.16

* NEW: console (~ to toggle)
* Stable but needs proper optimisation
* Summarised all files in /editor and /engine folders

---------------

### v1.0.15.0

* Optimised shaders
* Behind the scenes changes to prepare for Deferred Rendering path
* High DPI support

---------------

### v1.0.14.0

* Engine optimisations for ARM CPUs

---------------

### v1.0.13.0

* Initial (beta) support for Gun pickup
* Half-Life 2 style Entity I/O system & debugger
* Recent File history, Auto-saving
* Logic Entities (timers, gates and switches)
* Textures can now be applied to individual faces

---------------


### v1.0.12.5

* Increased terrain gen limits by 16x
* Improvements to texturing/tinting brushes
* Geometry and terrain looks good even with no textures (lo-fi feel)

  ---------------

### v1.0.12.0  |  Verdant_Meadow

* Improved renderer
* Added terrain generator and UI
* Finalised UI layout

  ---------------


### v1.0.11.0  |  Delicious-Toast

* First non-beta release
* Added Toast notification area to UI

  ---------------

```

I remember waiting for hours to run BSP, VIS and RAD on a map, 
Goal: brute-force frustum culling (every frame) with Snapdragon/Adreno 8CX


```




