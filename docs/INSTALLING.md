# How to prepare to use this code

The two main use cases are in simulation and with lab hardware; with the former
case being focused on a full simulation-based study or on validating the
experimental code, deployment, or other procedures (e.g. calibration, sensor
debugging etc).

The **lab-based** use case requires less setup (but of course assumes the
hardware is already prepared). First, install dependencies on the host PC:

    $ pip install -r requirements-lab.txt

Second, ensure that dependencies are installed on all of the SBC hosts for
the robots that will be used in the experiments.  The main dependency that has
not routinely been installed with new robots is `numpy`.  This can be installed
quickly via `apt-get install numpy` (since it is pre-compiled), and no
extremely recent features are used.

The **simulation-based** use case requires that the simulator is installed, and also the management tools.  Detailed instructions for deployable simulations
are provided on [readthedocs](https://assisipy.readthedocs.io/en/latest/install.html).  Additionally, ensure that the python dependencies are met on the 
host PC:

    $ pip install -r requirements-sim.txt



