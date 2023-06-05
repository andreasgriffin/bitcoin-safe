import bdkpython as bdk



    
class OutPoint(bdk.OutPoint): 
    def __key__(self):
        return tuple(v for k, v in sorted(self.__dict__.items()))    
    
    def __hash__(self):
        return hash(self.__key__())    
         
    @classmethod
    def from_bdk_outpoint(cls, bdk_outpoint:bdk.OutPoint):
        return OutPoint(bdk_outpoint.txid, bdk_outpoint.vout)

    @classmethod
    def from_str(cls, outpoint_str:str):
        txid, vout = outpoint_str.split(':')
        return OutPoint(txid, int(vout))




class AddressInfoMin():
    def __init__(self, address, index, keychain):
        self.address = address
        self.index = index
        self.keychain = keychain
    
        
    def __repr__(self) -> str:
        return str(self.__dict__)
    
    def __key__(self):
        return tuple(v for k, v in sorted(self.__dict__.items()))    
    
    def __hash__(self):
        return hash(self.__key__())    
         
    @classmethod
    def from_bdk_address_info(cls, bdk_address_info:bdk.AddressInfo):
        return AddressInfoMin(bdk_address_info.address.as_string(), bdk_address_info.index, bdk_address_info.keychain)
        
    def serialize(self):
        d = self.__dict__.copy()
        d["__class__"] = self.__class__.__name__
        return d
        
    @classmethod
    def deserialize(cls, dct):
        assert dct.get("__class__") == cls.__name__
        if "__class__" in dct:
            del dct["__class__"]
        return cls(**dct)
            
    
         
    
if __name__ == '__main__':
    testdict = {}
    def test_hashing(v):            
        testdict[v] = v.__hash__()
        print(testdict[v])    
    
    test_hashing(OutPoint('txid', 0))
    test_hashing(AddressInfoMin('ssss', 4, bdk.KeychainKind.EXTERNAL))
