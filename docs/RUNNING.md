# How to run bee-side setup in a virtual environment

1. See INSTALLING.md for the required packages and software.
2. The tool, `exec_sim_timed` from `assisipy-utils` launches the 
   robot code, and optionally simulated bees, in the `assisi-playground` 
   simulator.   The configuration file describes the code to be deployed,
   and the simulated agents and arenas. 
   An example command:

    $ exec_sim_timed --conf virt_2way.conf --rpt 1


# How to run bee-side setup with physical hardware

On account of the manual time-synchronisation with the fish-side, the
hardware-based experiments do not use the `exec_*_timed` functions.  Instead,
they use three deployment tools directly:

    # a) setup, before experiment
    $ cd configs/2way
    $ deploy.py enh_2way.assisi
    # b) execute at agreed launch time
    $ assisirun.py enh_2way.assisi 
    # c) wait for experiment to run, after completion run this
    $ collect_data.py enh_2way.assisi


More detailed notes are in the howto document on the project drive.



