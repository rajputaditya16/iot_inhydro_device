#!/bin/bash
export LD_LIBRARY_PATH="/home/anuj-prajapati/.local/lib:$LD_LIBRARY_PATH"
export TK_LIBRARY="/home/anuj-prajapati/.local/share/tcltk/tk8.6"
export PYTHONPATH="/home/anuj-prajapati/.local/lib/python3.14/site-packages:$PYTHONPATH"
exec python3 itc_polyhouse_controller.py "$@"
