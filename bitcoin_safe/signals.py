import threading
class Signal:
    def __init__(self, name=None):
        self.name = name 
        self.slots = []
        self.lock = threading.Lock()
                
    def connect(self, slot):
        with self.lock:
            self.slots.append(slot)
        
    def disconnect(self, slot):
        with self.lock:
            self.slots.remove(slot)
    
    def __call__(self, *args, **kwargs):
        return self.emit(*args, **kwargs)
    
    def emit(self, *args, **kwargs):
        responses = []
        if not self.slots:
            print(f'Signal {self.name}.emit() was called, but no listeners {self.slots} are listening.')
            
        with self.lock:
            for slot in self.slots:
                responses.append( slot(*args, **kwargs))
        return responses

class SingularSignal(Signal):
    def connect(self, slot):
        if not self.slots:
            super().connect(slot)
        else:
            raise Exception('Not allowed to add a second listener to this signal.')
    
    def emit(self, *args, **kwargs):
        responses = super().emit(*args, **kwargs)
        return responses[0] if responses else responses




from typing import List, Dict

class QTWalletSignals:
    def __init__(self) -> None:
        self.add_to_coincontrol = Signal('add_to_coincontrol')
        self.remove_from_coincontrol = Signal('remove_from_coincontrol')
        self.are_in_coincontrol = Signal('are_in_coincontrol')
        

from collections import defaultdict
class Signals:
    """
    The idea here is to define events that might need to trigger updates of the UI or other events  (careful of circular loops)
    
    State what happended, NOT the intention:
        
        Good signal:
            utxos_changed
        And to this signal a listener might be triggered:
            utxo_list.update()        
        
        A bad signal is:
            need_utxo_list_update
            
    
    I immediately break the rule however for SingularSignal, which is a function call
    """
    def __init__(self) -> None:
        self.utxos_updated = Signal('utxos_updated')
        self.addresses_updated = Signal('addresses_updated')
        self.labels_updated = Signal('labels_updated')        
        self.category_updated = Signal('category_updated')        
        self.completions_updated = Signal('completions_updated')        
        self.event_wallet_tab_closed = Signal('event_wallet_tab_closed')
        self.event_wallet_tab_added = Signal('event_wallet_tab_added')
        
        self.tx_from_text = SingularSignal('tx_from_text')
        self.update_all_in_qt_wallet = SingularSignal('update_all_in_qt_wallet')

        self.show_utxo = SingularSignal('show_utxo')
        self.show_address = SingularSignal('show_address')
        self.show_private_key = SingularSignal('show_private_key')

        self.show_transaction = SingularSignal('show_transaction')
        self.cpfp_dialog = SingularSignal('cpfp_dialog')
        self.dscancel_dialog = SingularSignal('dscancel_dialog')
        self.bump_fee_dialog = SingularSignal('bump_fee_dialog')
        self.show_onchain_invoice = SingularSignal('show_onchain_invoice')
        self.save_transaction_into_wallet = SingularSignal('save_transaction_into_wallet')
        
        self.qt_wallet_signals: Dict[str, QTWalletSignals] = defaultdict(QTWalletSignals)

        
    