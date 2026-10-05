import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from BRH_Test.website import create_app
app=create_app({'DATABASE_URL':'','SQLITE_PATH':str(ROOT/'output/video/assets/preview.db'),'SECRET_KEY':'video-preview-only','CLASSIFIER_AUTOLOAD':False,'SESSION_COOKIE_SECURE':False})
db=app.extensions['database']
uid=db.create_user('pilot@literally-trash.local','Pilot','')
for i,(label,category,score) in enumerate([('plastic water bottle','recycling',.87),('chip bag','trash',.82),('cardboard box','recycling',.91),('paper towel','trash',.84)]):
 db.add_detection('video-example-'+str(i),uid,label,category,False,score,'browser')
 db.add_collection(uid,category,1,'video-example-'+str(i),label)
app.run(host='127.0.0.1',port=8123,use_reloader=False)
