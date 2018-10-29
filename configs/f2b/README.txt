This is the deployment setup and individual casu controller setup for a
**fish to bee** experiment, and uses 2 bee arenas are independent of 
one another but each receive the same input from the fish side.

what happens here is:
- bee side is "open loop"
- recv input from fish
- do not transmit anything to fish

To ensure data arrives at both pairs of casus, the relay is modified to
duplicate all messages.  
