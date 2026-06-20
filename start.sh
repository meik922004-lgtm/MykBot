#!/usr/bin/env bash
python Main.py &
gunicorn dashboard:app