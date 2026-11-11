"""Point d'entree : installateur au premier lancement, application ensuite."""
import os
import subprocess
import sys

from cowork import env


def run():
    args = sys.argv[1:]
    if '--midi-setup' in args:
        from cowork import setup
        setup.midi_setup()
        return
    if '--uninstall' in args:
        from cowork import setup
        setup.uninstall()
        return
    installed = os.path.normcase(sys.executable) == os.path.normcase(env.INSTALLED_EXE)
    if '--install' in args or (env.FROZEN and not installed):
        from cowork import setup
        if setup.install(silent='--silent' in args) and env.FROZEN:
            subprocess.Popen([env.INSTALLED_EXE])
        return
    from cowork import app
    app.main(open_ui='--no-ui' not in args)


if __name__ == '__main__':
    run()
