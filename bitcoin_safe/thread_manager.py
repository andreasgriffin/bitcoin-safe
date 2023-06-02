import logging
logger = logging.getLogger(__name__)

import time
from concurrent.futures import ThreadPoolExecutor
import threading
    
class ThreadManager():    
    def __init__(self) -> None:
        self.futures = set()
        self.executor = ThreadPoolExecutor(max_workers=2)    
        self.write_lock = threading.Lock()

        
    def start_write_lock_thread(self, my_function, name='job', on_job_done=None):      
        return self.start_thread(my_function, name=name, on_job_done=on_job_done, lock=self.write_lock)
        
        
    def start_thread(self, my_function, name='job', on_job_done=None, lock=None):        
        if on_job_done is None:
            on_job_done = lambda future: logger.debug(f'{name} finished with result {future.result()}\nThere are {len(self.futures)} jobs in the queue')
        
        
        
        if lock:
            def decorated_function():
                with lock:
                    return my_function()
        else:
            decorated_function = my_function
        
        def outer_job_done(future):
            self.futures.discard(future)
            return on_job_done(future)
        
        
        future = self.executor.submit(decorated_function)
        future.add_done_callback(outer_job_done)
        self.futures.add(future)
        return future
        
        
    def stop(self):
        self.executor.shutdown(wait=True)
        


if __name__ == '__main__':

    def my_function():
        logger.debug('Start sleep')
        time.sleep(2)

        
    tm = ThreadManager()
    tm.start_locked_thread(my_function)
    tm.start_locked_thread(my_function)
    tm.start_locked_thread(my_function)
    tm.start_locked_thread(my_function)
    
    tm.stop()