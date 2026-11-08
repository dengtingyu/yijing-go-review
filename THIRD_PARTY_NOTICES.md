# Third-party components

- **KataGo** is a separate engine by David J. Wu and contributors. Engine and bundled dependency terms: https://github.com/lightvector/KataGo/blob/master/LICENSE . The setup script downloads the official release; binaries are not stored in this repository.
- The default **kata1-b18c384nbt-s9996604416-d4316597426** model is downloaded from the official training server. Its separate neural network license is available at https://katagotraining.org/network_license/ . Model weights are not stored in this repository.
- **sgfmill 1.1.1** by Matthew Woodcraft is an installed Python dependency, under the MIT license: https://mjw.woodcraft.me.uk/sgfmill/ .
- **Three.js 0.160.1** and its **OrbitControls**, Copyright 2010–2023 Three.js Authors, MIT: vendored in `web/vendor/`, with the license in `web/vendor/THREE-LICENSE.txt`. Obtained from the version-pinned npm distribution via jsDelivr. OrbitControls' bare `three` import is changed to the local `./three.module.js` path; apart from whitespace cleanup, the upstream sources are unchanged. Upstream: https://github.com/mrdoob/three.js/tree/r160 .

Yijing is an independent interface. It is not affiliated with KataGo, LizzieYzy, KaTrain, or Golaxy/星阵. No code or assets from those graphical interfaces are bundled here.
