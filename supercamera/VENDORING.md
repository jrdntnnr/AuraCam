# Vendored supercamera driver

This package is copied from
[Revise-Robotics/supercamera-endoscope](https://github.com/Revise-Robotics/supercamera-endoscope)
at commit `2a9ad9443cbfa177a0eee0d6570a06639e9a40d7`. It is MIT licensed.

Vendoring the small pure-Python driver makes first boot deterministic and keeps
the existing `protocol_camera.Camera` extensions working without a PyPI fetch.

