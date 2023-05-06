
    
import cProfile
from pstats import Stats, SortKey


from .bitcoin_safe_main import main
import asyncio

    
    

if __name__ == '__main__':
    from .util import DEVELOPMENT_PREFILLS
    do_profiling =  DEVELOPMENT_PREFILLS
    if do_profiling:
        with cProfile.Profile() as pr:
            asyncio.run(main())      

        with open('profiling_stats.txt', 'w') as stream:
            stats = Stats(pr, stream=stream)
            stats.strip_dirs()
            stats.sort_stats('time')
            stats.dump_stats('.prof_stats')
            stats.print_stats()
    else:
        asyncio.run(main())      
