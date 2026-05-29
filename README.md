<img src="https://github.com/user-attachments/assets/946ba690-52e7-4f7c-bbd2-f92a7442bca8" width="375">




<img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="MIT License">  <img src="https://img.shields.io/badge/status-Active%20Development-orange?style=for-the-badge" alt="Status">

### _A tooling-first 3D engine and brush-based CSG level editor inspired by Radiant and Hammer_
### Built for rapid creation of strange, playable spaces.

**Key Features**
- Hit "play" instantly: no import, compile or bake step
- Generate fully playable procedural liminal maps with one click
- Entity I/O logic system inspired by Source engine
- Classic brush-based CSG editing
- Export creations as self-contained shareable packages
- Local split-screen multiplayer - Two players with a single keyboard (or gamepad)
- **Designed to bring back the immediacy of classic Radiant/Worldcraft workflows**

### [💾 Download Binaries (Win/macOS)](https://github.com/ViciousSquid/Fio/releases) || [Wiki](https://github.com/ViciousSquid/Fio/wiki/) || [Changelog](https://github.com/ViciousSquid/Fio/wiki/changelog)
#### Linux: use the included Dockerfile or [run from source](https://github.com/ViciousSquid/Fio#-quickstart)
<img width="2039" height="1119" alt="image" src="https://github.com/user-attachments/assets/a68a33ac-1da7-4626-8796-46a6435cf95c" />




 ------------------------

### Logic & Gameplay
- Entity I/O system (Half-Life 2–style wiring model)
- GUI assistant for generating gameplay logic and level setups
- 19 included example maps
- NPCs / monsters
- Node-based pathfinding
- Triggers, timers, and logic gates

### Rendering
- OpenGL 3.3 forward renderer
- Dynamic lighting with shadows
- Fog, glass, water, overbright effects
- Frustum culling
- Dynamic portals (moveable / scripted transforms)

### Architecture
- Editor layer: PyQt-based tool suite + asset browser
- Engine layer: rendering, physics, AI
- Modular system design (fully open source, MIT licensed)

### Technical Targets
- Python 3.10+
- Multi-threaded
- Optimized for Windows-on-ARM (Snapdragon 8cx-class devices)
- Stable 60 FPS target on mid-range hardware

🗎 Modular architecture, fully open source (MIT License)


  ------------------------------

 ## Why Fio exists

Fio is built as:
- a rendering experimentation platform
- a level editor inspired by classic BSP workflows
- a systems-driven engine with tooling-first design

Fio removes the editor/runtime boundary that most engines enforce

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

<img width="1609" height="1119" alt="image" src="https://github.com/user-attachments/assets/22283623-21a2-4776-a2ae-71649f5276f0" />

----------------

<img width="1875" height="1697" alt="image" src="https://github.com/user-attachments/assets/ce564bef-3e9d-4bc5-a93a-e9628638cadb" />




