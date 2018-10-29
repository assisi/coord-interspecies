
import pygraphviz as pgv
import os


def get_outmap(fg, casu, verb=False):
    '''
    given the flattened graph, `fg`, find a map of connections for
    which the node `casu` should emit messages to.

    return a dict whose keys are the destinations and whose values
    are edge labels

    '''
    if casu not in fg:
        raise KeyError

    sendto = {}

    for src, _dest in fg.out_edges(casu):
        # attributes does not have a .get(default=X) so make useable copy
        attr = dict(fg.get_edge(src, _dest).attr)
        lbl = attr.get('label')
        # trim any layer info from the edge src/dest
        dest = str(_dest).split('/')[-1]

        if verb: print "\t--> {} label: {}".format(dest, lbl)
        sendto[dest] = lbl

    return sendto

def get_inmap(fg, casu, default_weight=None, verb=False):
    '''
    given the flattened graph, `fg`, find a map of connections for
    which the node `casu` may receive messages from

    return a dict whose keys are the sources and whose values are
    dicts with entries for labels and edgeweight.

    the value of `default_weight` is set on all weights if one is not
    specified in the graph file


    '''
    if casu not in fg:
        raise KeyError

    recvfrom = {}
    # and a map of incoming weights
    if verb: print "expect to receive from..."
    for src, dest in fg.in_edges(casu):
        attr = dict(fg.get_edge(src, dest).attr)
        lbl = attr.get('label')
        _w = attr.get('weight', default_weight)
        if _w is None:
            if verb: print "[I] this edge has no weight, not regular net"
            continue
        else:
            w = float(_w)

        if verb: print "\t<-- {} w={:.2f} label: {}".format(src, w, lbl)
        recvfrom[src] = { 'w': w, 'label': lbl }

    return recvfrom




def show_inout(nbg):
    '''
    convenience function to display the comm network available to this casu
    according to the nbg file. Accepts a pygraphviz graph.
    '''

    for casu in nbg.nodes():
        print "\n*** {} ***".format(casu)

        # need to know who will send to
        my_sendto = []
        my_recvfrom = []
        print "Send to..."
        for src, _dest in nbg.out_edges(casu):
            # attributes set is like a dict but without get+default
            # - so make a copy that is useable.
            attr = dict(nbg.get_edge(src, _dest).attr)
            lbl = attr.get('label')
            # strip layer (if multi-layered) - not needed here
            dest = str(_dest).split('/')[-1]

            print "\t--> {} label: {}".format(dest, lbl)
            my_sendto.append(dest)

        # and a map of incoming weights
        print "expect to receive from..."
        for src, dest in nbg.in_edges(casu):
            attr = dict(nbg.get_edge(src, dest).attr)
            lbl = attr.get('label')
            w = float(attr.get('weight', 0.0))

            print "\t<-- {} w={:.2f} label: {}".format(src, w, lbl)
            my_recvfrom.append(src)


def flatten_AGraph(nbg):
    '''
    process a multi-layer CASU interaction graph file and return
    a flattened graph.

    Note: does not support node properties!
    '''
    g = pgv.AGraph(directed=True, strict=False) # allow self-loops.

    for _n in nbg.nodes():
        # trim any layer info off the node
        n = _n.split('/')[-1]
        g.add_node(n)


    for i, (_src, _dest) in enumerate(nbg.edges()):
        # trimmed versions (stripped off the layer)
        s = _src.split('/')[-1]
        d = _dest.split('/')[-1]

        # if it doesn't exist already, add edge
        if not (s in g and d in g):
            print "[W] s,d not both present. not adding edge"
            continue
        #else:
        #    print "[I] adding {} -> {} ({} : {})".format(
        #        s, d, s.split('-')[-1], d.split('-')[-1])

        g.add_edge(s, d)
        #print "now we have {} edges (pre: {}, delta {})\n".format(
        #    pre, post, post-pre)

        # add any attributes to the flattened graph
        attr = dict(nbg.get_edge(_src, _dest).attr)

        e = g.get_edge(s, d)
        for k, v in attr.iteritems():
            e.attr[k]= v

    return g



if __name__ == "__main__":
    ''' mini test script '''

    # load test nbg file (including layers)
    f_nbg = "graz_setup.nbg"
    nbg = pgv.AGraph(os.path.join("../", "2way_virt", f_nbg))

    # flatten /strip out layers
    g2 = flatten_AGraph(nbg)
    # pick an arbitrary casu and show info
    casu = g2.nodes()[0]
    imap = get_inmap(g2, casu)
    omap = get_outmap(g2, casu)

    print casu, imap, omap

    # also show comparisons of layered vs flattened graphs
    if 1:
        print "=" * 60
        show_inout(nbg)
        print "\n\n"
        print "=" * 60
        show_inout(g2)

