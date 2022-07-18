""" This script post-hoc strips some specific strings from all the downloaded files as a file-name cleanup operation to keep things brief and to the point. """

import os
import sys
import glob

STRIP_STR = {'gutenacht':('gutenachtmitdermaus_',),
             'hoerspiel':('maushoerspiel_',),
             'podcast'  :('diesendungmitdermauszumhoeren_', 'diemauszumhoeren_',),
             'musik'    :('diesendungmitdermauszumhoerenmusik_', 'diemauszumhoerenmusik_',),
            }

for root, dirs, files in os.walk(".", topdown=False):
   for name in files:
      if os.path.basename(root) in STRIP_STR:
          stripstr_category = os.path.basename(root)
          old = os.path.join(root, name)
          for to_replace in STRIP_STR[stripstr_category]:
              if to_replace in name:
                  new = os.path.join(root, name.replace(to_replace, ''))
                  
                  print(stripstr_category,' : ' , old, ' -> ' , new)
                  if '-d' in sys.argv: print('    skipping renaming operation due to given command line parameter "-d", which executes a dry-run.')
                  else: os.rename(old, new)
                  break
