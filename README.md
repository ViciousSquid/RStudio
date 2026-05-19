<img src="https://github.com/user-attachments/assets/946ba690-52e7-4f7c-bbd2-f92a7442bca8" width="375">




<img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="MIT License">  <img src="https://img.shields.io/badge/status-Active%20Development-orange?style=for-the-badge" alt="Status">

### _A modular 3D engine and brush-based CSG level editor inspired by Radiant and Hammer, with runtime-switchable forward and deferred rendering, a shared shader system, and a HL2-style entity I/O pipeline._

**Key Features**
- 🔁 Runtime-switchable Forward & Deferred rendering
- 🎨 Unified shader system across pipelines
- 🧠 Half-Life 2–style Entity I/O logic system
- 🧱 Classic brush-based CSG editing
* Designed to bring back the immediacy of classic Radiant/Worldcraft workflows.

### [Download for macOS and Windows](https://github.com/ViciousSquid/Fio/releases) | [Getting Started](https://github.com/ViciousSquid/Fio/wiki/Getting-started--&-Basic-Navigation) | [Changelog](https://github.com/ViciousSquid/Fio/wiki/changelog)
#### Linux: use the included Dockerfile or [run from source](https://github.com/ViciousSquid/Fio#-quickstart)
<img width="2039" height="1119" alt="image" src="https://github.com/user-attachments/assets/a68a33ac-1da7-4626-8796-46a6435cf95c" />




 ------------------------

### Core Workflow
- Editor and engine run as a unified environment
- Hit play instantly — no compile or bake step
- Iterate on gameplay and logic in real-time
- Design, test, and refine in a single environment
- Creations can be published and shared

### Logic & Gameplay
- Entity I/O system (Half-Life 2–style)
- Visual scripting (25 examples)
- NPCs/monsters
- Node pathfinding
- Logic Gates, Triggers, Timers

### Rendering
- Dual rendering pipelines (Forward & Deferred, switchable at runtime)
- Real-time dynamic lighting with shadows
- Fog, glass, water and overbright shaders
- Moving and rotating brushes
- World Portals (Prey 2006 style)
- Frustum culling

### Technical
- JSON level format
- OBJ model support
- OpenGL 3.3 target
- Optimized for Snapdragon 8CX / Windows-on-ARM

🗎 Modular architecture, fully open source (MIT License)


  ------------------------

<img width="1609" height="1119" alt="image" src="https://github.com/user-attachments/assets/22283623-21a2-4776-a2ae-71649f5276f0" />



  ------------------------------
 ## Architecture Overview

Fio is structured as:

- Editor Layer (PyQt UI, tools, asset browser)
- Engine Layer (rendering, physics, AI)
- Rendering System
  - BaseRenderer (shared interface)
  - Forward and Deferred pipelines (runtime-switchable)
  - Shared shader system

 ## Why Fio exists

Most Python 3D engines focus on simplicity or education.

Fio is built as:
- a rendering experimentation platform
- a level editor inspired by classic BSP workflows
- a systems-driven engine with tooling-first design

------------------------------

 #### 🚀 Quickstart:

 Python 3.10+ is required
 
 1. Clone and Enter the Directory:
```bash
git clone https://github.com/ViciousSquid/Fio.git
cd Fio
```
2. Setup Virtual Environment (Recommended)
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```
3. Install Dependencies:
```bash
pip install -r requirements.txt
```
4. Launch the Editor:
```bash
python main.py
```
   

  -----------------------------

  ### 🤝 Contributing
Contributions, feedback, and experiments are welcome. Check issues or open a discussion.


<img width="1875" height="1697" alt="image" src="https://github.com/user-attachments/assets/ce564bef-3e9d-4bc5-a93a-e9628638cadb" />



