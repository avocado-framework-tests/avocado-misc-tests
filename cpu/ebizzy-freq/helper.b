#!/usr/bin/bc 
define get_a (records,load){
        auto tmp,at
        scale = 0;
        at = ( ( records * load ) / 100 );
        return at;
}


define get_i (records,load){
        auto tmp,delay
        scale = 0;
        tmp = 100 - load;
        delay = tmp * 10000 ;
        return delay;
}
