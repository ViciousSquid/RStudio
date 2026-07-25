<img src="https://github.com/user-attachments/assets/946ba690-52e7-4f7c-bbd2-f92a7442bca8" width="375">




<img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="MIT License">  <img src="https://img.shields.io/badge/status-Active%20Development-orange?style=for-the-badge" alt="Status">

## Fio — Liminal World Editor & Procedural Engine

### Unified editor and runtime inspired by Radiant and Hammer.
**Engineered on low-power ARM hardware to eliminate unnecessary work before relying on faster hardware.**

**Key Features**
- Edit and play in the same runtime
- Hit "play" instantly: no import, compile or bake step
- Generate fully playable procedural maps with two clicks
- Entity I/O logic system inspired by Source engine
- Classic brush-based editing with arbitrary convex polyhedra
- Non-Euclidean portal connections between any two points in a level
- Export creations as self-contained packages
- Local split-screen multiplayer
- **Designed to bring back the immediacy of classic Radiant/Worldcraft workflows**

### [💾 Download Binaries for Windows/macOS/Linux](https://github.com/ViciousSquid/Fio/releases)  
### Documentation: [Wiki](https://github.com/ViciousSquid/Fio/wiki/) | [Changelog](https://github.com/ViciousSquid/Fio/wiki/changelog)
#### or use the included Dockerfile or [run from source](https://github.com/ViciousSquid/Fio#-quickstart)

<img src="https://github.com/user-attachments/assets/a68a33ac-1da7-4626-8796-46a6435cf95c" width="800">




 ------------------------

 
 ## Why Fio exists

Fio explores a unified approach to level editing and runtime simulation:

- Reducing friction between authoring and execution
- Reintroducing brush/CSG-based workflows in a modern runtime
- Treating gameplay logic as a visible, editable system
- Supporting rapid experimental iteration in rendering and world design
- Enabling native non-Euclidean level design via world portals
- Decision tracking/branching narratives: maps can affect other maps

  -----------------

### Logic & Gameplay
- 16 included *example maps*
- Monsters with node-based pathfinding
- Triggers, timers, and logic gates
- Procedural terrain and liminal level generators
- Keys/values can be stored globally (persists across level changes)

### Rendering
- Lean OpenGL 3.3 renderer engineered for performance and broad compatibility.
- Dynamic lighting, shadows, fog, glass and water
- Frustum culling
- **World portals** — non-Euclidean view-through portals with stencil-buffer masking, 
  oblique near-plane clipping, and I/O-driven fade transitions. Place two portals, 
  link them by name, walk through seamlessly.

### Under the Hood
- **Python 3.10+ Core:** High-level logic and orchestration paired with C-accelerated NumPy arrays for vector math, scene transformations, and batch numeric processing.
- **Hardware-Conscious Design:** Optimized for low-power, ARM-class CPUs—minimizing unnecessary memory allocations and redundant compute cycles before leaning on raw GPU power.
- **Zero Serialization Overhead:** Editor and engine share the same runtime memory state, enabling instant execution with no compile, bake, or scene-deserialization delay.
- **Modular Multi-Threading:** Subsystems (render pipeline, physics, and world simulation) are strictly decoupled to keep framerates steady during heavy runtime tasks.
- **Open Architecture:** Fully open-source, modular codebase (MIT License) designed for easy extendability and low-level experimentation.

------------------------------

 #### 🚀 Quickstart:

 Python 3.10+ is required
 
```bash
git clone https://github.com/ViciousSquid/Fio.git
cd Fio
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate (Windows)
pip install -r requirements.txt
python main.py
```
   

  -----------------------------

  ### 🤝 Contributing
Contributions, feedback, and experiments are welcome. Check issues or open a discussion.

----------------



<img src="https://github.com/user-attachments/assets/c6c6b036-2425-4508-a2fe-05816429303f" width="800"><br>

<img src="https://raw.githubusercontent.com/ViciousSquid/Fio/1.3.0.0_Latest/assets/__portal.gif" width="800">

<img src="https://github.com/ViciousSquid/Fio/blob/1.3.1.0_M4_rev2_Latest/assets/__portal.gif?raw=true" width="450">

<img src="https://github.com/user-attachments/assets/22283623-21a2-4776-a2ae-71649f5276f0" width="700">





