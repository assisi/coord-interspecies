#!/bin/bash

# quick script to check whether a bbg is out of space (<30mb is too little 
# for a bbg that hosts 4 casus).  This list covers the current arena/ system as
# of June 2017

hostlist=bbg-012 bbg-002 bbg-011 bbg-001 bbg-006 bbg-005 bbg-004 bbg-008 

for bbg in ${hostlist}; 
do 
    ssh -q ${bbg} "usr=\$(whoami); host=\$(echo \$HOSTNAME); avail=\$(df -hk . | tail -n1 | tr -s ' ' | cut -d' ' -f4); availH=\$(df -h . | tail -n1 | tr -s ' ' | cut -d' ' -f4); reqd=30720; if [ "\$avail" -gt "\$reqd" ]; then ok="OK"; else ok="Insufficient space"; fi; echo  \${usr}@\${host}: \${avail}kb ==\${availH}==  \${ok} ;" ;
done

