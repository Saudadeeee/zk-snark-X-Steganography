pragma circom 2.0.0;

template StegoCheck() {
    signal input message[8];      
    signal input secret[16];      
    signal input slots[256];      
    signal output valid;
    
    signal secretNum;
    secretNum <== secret[0] + secret[1]*2 + secret[2]*4 + secret[3]*8 + 
                  secret[4]*16 + secret[5]*32 + secret[6]*64 + secret[7]*128 +
                  secret[8]*256 + secret[9]*512 + secret[10]*1024 + secret[11]*2048 +
                  secret[12]*4096 + secret[13]*8192 + secret[14]*16384 + secret[15]*32768;
    
    for (var i = 0; i < 8; i++) {
        message[i] * (1 - message[i]) === 0;
    }
    
    for (var i = 0; i < 16; i++) {
        secret[i] * (1 - secret[i]) === 0;
    }
    
    signal boundCheck;
    boundCheck <== 248 - secretNum;
    
    valid <== 1;
}

component main = StegoCheck();