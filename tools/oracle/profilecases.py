"""profile.c's cases through imdriver's profile command: EXIF, 8BIM and XMP blobs built byte by
byte, each sized at or around one of the bounds SyncExifProfile, Sync8BimProfile,
GetProfilesFromResourceBlock, WriteTo8BimProfile, Update8BIMClipPath and the XMP helpers test.
cases.py imports CASES: (name, driver arguments, case files). Built here, not stored: two of them
are 225 KB. Each op's meaning is in imdriver.c's ProfileCmd; the bytes are printed after every op,
so a write the mutant skips or misplaces shows. Names, not comments, say what each one aims at:

  exif-fit       an IFD with no room for its next pointer: the (length-6)/12 entry bound
  exif-ptr       Exif offsets to 0, length-2, length-1 and out of range, before the orientation
  exif-early     a long tag that leads into the Exif IFD before the Exif offset does
  exif-overlap   nested IFDs whose last one overlaps the Exif IFD's entries (they are then seen
                 as visited): the nesting limit decides whether PixelXDimension is written
  exif-level     the same with a next-IFD pointer, for the next pointer's nesting limit
  exif-big       an IFD at offset 0 (needs 0x4949 entries: 225 KB) and a next pointer misread at
                 65536 (64 KB); the hex is read from a file, an argument may not exceed 128 KB
  8bim-*         resources of size 0, ending exactly at the block's end, names that cover the
                 rest, and a resolution resource after an empty one
  clip, clip2    clipping paths with ids 1999..2999, a name that hides a path, a 2-byte tail
  xmp, xmp-y     resolutions as fractions; a YResolution without an XResolution
"""
import struct

def P(e,fmt,*v): return struct.pack(('<' if e=='II' else '>')+fmt,*v)
def tiff(e, ifds, size):
    """ifds: {offset: (entries, next)}; entries (tag, fmt, count, value4bytes)"""
    b=bytearray(size); b[0:2]=e.encode(); b[2:4]=P(e,'H',42); b[4:8]=P(e,'I',min(ifds) if ifds else 8)
    for o,(ents,nx) in ifds.items():
        b[o:o+2]=P(e,'H',len(ents))
        for i,(t,f,c,v) in enumerate(ents):
            q=o+2+12*i; b[q:q+8]=P(e,'HHI',t,f,c); b[q+8:q+12]=v
        if nx is not None and o+2+12*len(ents)+4<=size: b[o+2+12*len(ents):o+6+12*len(ents)]=P(e,'I',nx)
    return bytes(b)
def S(e,v): return P(e,'H',v)+b'\0\0'
def L(e,v): return P(e,'I',v)
def std(e):
    ifd0=[(0x100,3,1,S(e,1)),(0x101,4,1,L(e,2)),(0x11a,5,1,L(e,100)),(0x11b,5,1,L(e,108)),(0x8769,4,1,L(e,116)),(0x112,3,1,S(e,1)),(0x128,4,1,L(e,2))]
    sub=[(0xa002,4,1,L(e,3)),(0xa003,3,1,S(e,4)),(0xa005,4,1,L(e,160))]
    inter=[(0x0001,2,4,b'R98\0')]
    ifd1=[(0x100,3,1,S(e,9)),(0x112,3,1,S(e,9))]
    return tiff(e,{8:(ifd0,180),116:(sub,0),160:(inter,0),180:(ifd1,0)},200)
def H(b): return b.hex()
def res8(i,data,name=b''):
    nm=bytes([len(name)])+name
    if len(nm)%2: nm+=b'\0'
    r=b'8BIM'+struct.pack('>H',i)+nm+struct.pack('>I',len(data))+data
    if len(data)%2: r+=b'\0'
    return r
FIELDS=['geom=70x50','res=300,150','units=2','orient=6']
V={}
V['exif-std']=['set=exif:'+H(std('II')),'set=app1:'+H(std('MM'))]+FIELDS+['sync','clone','remove=app1']
V['exif-prefix']=['set=exif:'+H(b'xyExif\0\0'+std('II'))]+FIELDS+['sync','set=exif:'+H(b'Exif\0\0'+std('MM')[:10]),'sync']
# exact-fit IFD without next pointer: (dl-6)/12 check
def exact(e,n_extra=0):
    ents=[(0x112,3,1,S(e,1)),(0x128,3,1,S(e,1))]
    return tiff(e,{8:(ents,None)},8+2+12*len(ents)+n_extra)
V['exif-fit']=['set=exif:'+H(exact('II',0)),'orient=6','units=2','sync','set=exif:'+H(exact('MM',4)),'sync','set=exif:'+H(exact('II',3)),'sync']
# ExifOffset to 0, to length-2, to length-1: orientation after it in IFD0
def ptr(e,target,size=64):
    ents=[(0x8769,4,1,L(e,target)),(0x112,3,1,S(e,1))]
    return tiff(e,{8:(ents,0)},size)
V['exif-ptr']=['orient=6']+sum((['set=exif:'+H(ptr('II',t)),'sync'] for t in (0,62,63,64,40)),[])
# format 0, format 12, format 13 (no), components negative
def fmt(e,f):
    ents=[(0x112,f,1,S(e,1)),(0x128,3,1,S(e,1))]
    return tiff(e,{8:(ents,0)},48)
V['exif-fmt']=['orient=6','units=2']+sum((['set=exif:'+H(fmt('II',f)),'sync'] for f in (0,1,12)),[])
# data offsets: xres rational at offset 0, at length-8 (exact end), at length-4 (overrun), at length-7
def data(e,off,size=64):
    ents=[(0x11a,5,1,L(e,off)),(0x112,3,1,S(e,1))]
    return tiff(e,{8:(ents,0)},size)
V['exif-data']=['res=300,150','orient=6']+sum((['set=exif:'+H(data('II',o)),'sync'] for o in (0,56,57,60,48)),[])
# sub IFD claims 2 entries with room only for 1 (+ next)
def claim(e):
    ents=[(0x8769,4,1,L(e,40)),(0x112,3,1,S(e,1))]
    b=bytearray(tiff(e,{8:(ents,0)},40+2+12+4))
    b[40:42]=P(e,'H',2); b[42:54]=P(e,'HHI',0xa002,4,1)+L(e,3)
    return bytes(b)
V['exif-claim']=['geom=70x50','set=exif:'+H(claim('II')),'sync','set=exif:'+H(claim('MM')),'sync']
# interop / other long tags as offsets; next-IFD pointers at the bounds
def longs(e,nx):
    ents=[(0x101,4,1,L(e,30)),(0xa005,4,1,L(e,44)),(0x112,3,1,S(e,1))]
    b=tiff(e,{8:(ents,nx)},80)
    return b
V['exif-longs']=['geom=70x50','orient=6']+sum((['set=exif:'+H(longs('II',n)),'sync'] for n in (0,60,78,79,80)),[])
# dimension boundaries
def dims(e,f):
    ents=[(0x100,f,1,S(e,1) if f==3 else L(e,1)),(0x101,f,1,S(e,1) if f==3 else L(e,1)),(0x100,f,2,L(e,0))]
    return tiff(e,{8:(ents,0)},64)
V['exif-dims']=sum((['geom=%dx%d'%g,'set=exif:'+H(dims('MM',3)),'sync','set=exif:'+H(dims('II',4)),'sync'] for g in ((65535,65536),(4294967295,4294967296),(70,50))),[])
# deep chain of ExifOffsets
def chain(e,n):
    ifds={}
    for k in range(n):
        o=8+20*k; ifds[o]=([(0x8769,4,1,L(e,o+20))],0)
    o=8+20*n; ifds[o]=([(0xa002,4,1,L(e,3)),(0x112,3,1,S(e,1))],0)
    return tiff(e,ifds,o+2+24+4+8)
V['exif-chain']=['geom=70x50','orient=6']+sum((['set=exif:'+H(chain('II',n)),'sync'] for n in (5,6,7,8)),[])
# 8BIM
ex=std('MM'); xmp=b'<x><tiff:XResolution>1</tiff:XResolution><tiff:YResolution>1</tiff:YResolution><tiff:ResolutionUnit>1</tiff:ResolutionUnit><tiff:Orientation>1</tiff:Orientation></x>'
blk=res8(0x3ed,bytes(16))+res8(0x404,b'\x1c\x02\x05ab',b'n')+res8(0x40c,b'tt',b'nm')+res8(0x422,ex)+res8(0x424,xmp)+res8(0x7777,b'z')+res8(0x40f,b'notanicc')
V['8bim']=['set=8bim:'+H(blk),'res=300,150','units=2','geom=70x50','orient=6','sync','set=xmp:'+H(b'<y/>'),'set=iptc:'+H(b'\x1c\x02\x05abc'),'set=icc:'+H(b'q'),'set=8bim:'+H(res8(0x3ed,bytes(16))),'units=1','sync']
V['8bim-zero']=['set=8bim:'+H(res8(0x404,b'',b'')+res8(0x404,b'\x1c\x02\x05ab')+bytes(12)),'set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x424,b'')),'set=xmp:'+H(b'<z/>'),
               'set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x424,b'abcd')),'set=xmp:'+H(b'<a/>'),'set=xmp:'+H(b'<b>1</b>')]
over=res8(0x7777,b'q'*20)+b'8BIM'+struct.pack('>H',0x404)+b'\0\0'+struct.pack('>I',10)+b'\x1c\x02\x05ab'
V['8bim-over']=['set=8bim:'+H(over),'set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x404,b'\x1c\x02\x05abc')),'set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x404,b'\x1c\x02\x05abcd'))]
# Sync8Bim boundaries: resource near end, name length vs length
def s8(nmlen,count,data_len,id_=0x3ed): 
    return b'8BIM'+struct.pack('>H',id_)+bytes([nmlen])+b'n'*nmlen+(b'' if nmlen%2 else b'\0')+struct.pack('>I',count)+bytes(data_len)
V['8bim-sync']=['res=300,150','units=2']+sum((['set=8bim:'+H(b),'sync'] for b in (s8(0,16,16),s8(0,16,15),s8(1,16,16),s8(3,16,16),b'8BIM\x03\xed'+b'\0'*5,b'8BIM\x03\xed'+b'\0'*6,
     b'8BIM\x03\xed\x02nn'+b'\0'*4, b'8BIM\x03\xed\x03nn')),[])
# clip paths
knot=struct.pack('>H',0)+struct.pack('>H',1)+bytes(22)+struct.pack('>H',1)+struct.pack('>6i',1<<23,1<<23,1<<22,1<<22,1<<21,1<<21)
clip=res8(1999,knot)+res8(2000,knot)+res8(2998,knot)+res8(2999,knot)
V['clip']=['set=8bim:'+H(clip),'clip=64x48:32x24+8+4','set=8bim:'+H(b'8BIM\x07\xd0\x02ab'+struct.pack('>I',len(knot))+knot),'clip=64x48:32x24+8+4',
           'set=8bim:'+H(b'8BIM\x07\xd0\x05abcde'+struct.pack('>I',len(knot))+knot),'clip=64x48:16x12+0+0',
           'set=8bim:'+H(b'8BIM\x07\xd0\x00\x00'+struct.pack('>I',len(knot)+1)+knot),'clip=64x48:16x12+0+0']
# XMP
xr=lambda v:'res=%s,%s'%(v,v)
V['xmp']=['set=xmp:'+H(xmp)]+sum(([xr(v),'sync'] for v in ('72','0.5','33.3333333333','1e-13','1e30','0.1','2.718281828459045','1e-12')),[])+[
  'res=72,96','sync','set=xmp:'+H(b'tiff:XResolution>1<'),'sync','set=xmp:'+H(b'<tiff:XResolution'),'sync','set=xmp:'+H(b'x<tiff:XResolution>'),'sync',
  'set=xmp:'+H(b'<tiff:XResolution>3</tiff:XResolution><?xpacket end="w"?>garbage'),'sync','set=xmp:'+H(b'<?xpacket end="w"?>'),
  'artifact=xmp:validate:true','set=xmp:'+H(b'<not xml'),'set=xmp:'+H(b'<ok/>')]
V['set']=['set=exif:','set=app1:'+H(b'Exif'),'set=app1:'+H(b'Exif\0'),'set=app1:'+H(b'MM'),'set=exif:'+H(b'MMx'),'set=app1:'+H(b'II*\0'),'set=icc:'+H(b'xy'),
          'append=icc:test:one','append=icc:test:two','append=nosuch:test:three','append=icc:empty:']
V['limit']=['set=iptc:'+H(b'a'*64),'set=iptc:'+H(b'b'*65),'acquire=64','acquire=65','set=exif:'+H(b'II'+bytes(62)),'set=exif:'+H(b'II'+bytes(63))]
FILES={'limit':{'.config/ImageMagick/policy.xml':'<policymap>\n  <policy domain="system" name="max-profile-size" value="64"/>\n</policymap>\n'}}

def fmt0(e):
    ents=[(0x112,0,0,S(e,1)),(0x128,3,1,S(e,1))]
    return tiff(e,{8:(ents,0)},48)
V['exif-fmt0']=['orient=6','units=2','set=exif:'+H(fmt0('II')),'sync','set=exif:'+H(fmt0('MM')),'sync']
# a single-long tag before ExifOffset that points at the Exif IFD: followed as a plain IFD (mutant), its entries marked
def early(e):
    ents=[(0x9999,4,1,L(e,60)),(0x8769,4,1,L(e,60)),(0x112,3,1,S(e,1))]
    sub=[(0xa002,4,1,L(e,3)),(0xa003,3,1,S(e,4))]
    return tiff(e,{8:(ents,0),60:(sub,0)},100)
V['exif-early']=['geom=70x50','orient=6','set=exif:'+H(early('II')),'sync','set=exif:'+H(early('MM')),'sync']
V['8bim-count0']=['set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x7778,b'')+res8(0x424,b'abcdef')+res8(0x7777,b'zzzz')),'set=xmp:'+H(b'<c/>'),
                  'set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x424,b'abcdef')),'set=xmp:'+H(b'<d/>'),
                  'set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x7778,b'')+res8(0x404,b'\x1c\x02\x05ab')+res8(0x7777,b'zzzz'))]
V['validate']=['artifact=xmp:validate:true','set=iptc:'+H(b'\x1c\x02\x05abc'),'set=icc:'+H(b'qq'),'set=xmp:'+H(b'<x/>'),'set=xmp:'+H(b'<not xml'),'set=xmp:'+H(b'<y>1</y>')]
# chains with an IFD overlapping the Exif IFD's second entry at the end: marks it visited
def overlap(e,depth,nexts=False):
    # ifd0 at 8: [ExifOffset->C1, ExifOffset->E, orientation]; E at 400: [dummy long 0x00010000, PixelX]
    E=400
    ifd0=[(0x8769,4,1,L(e,40)),(0x8769,4,1,L(e,E)),(0x112,3,1,S(e,1))]
    ifds={8:(ifd0,0)}
    o=40
    for k in range(depth):
        nxt=o+20 if k<depth-1 else E+12
        ifds[o]=([(0x8769,4,1,L(e,nxt))],(E+12 if nexts else 0)); o+=20
    ifds[E]=([(0x7777,4,1,L(e,0x00010000) if e=='II' else P(e,'I',0x00000100)),(0xa002,4,1,L(e,3))],0)
    return tiff(e,ifds,E+2+24+4+16)
V['exif-overlap']=['geom=70x50','orient=6']+sum((['set=exif:'+H(overlap('II',d)),'sync'] for d in range(1,17)),[])
V['exif-overlap-next']=['geom=70x50','orient=6']+sum((['set=exif:'+H(overlap('II',d,True)),'sync'] for d in (1,2,5,10,12,13,14,15)),[])

V['xmp-y']=['set=xmp:'+H(b'<tiff:YResolution>1</tiff:YResolution>'),'res=72,72','sync','res=72,96','sync']
V['8bim-sync0']=['res=300,150','units=2','set=8bim:'+H(res8(0x7777,b'')+res8(0x3ed,bytes(16))),'sync']
rec0=struct.pack('>HH',0,1)+bytes(22)
inner=struct.pack('>I',52)+rec0+knot[0:0]+struct.pack('>H',1)+struct.pack('>6i',1<<23,1<<23,1<<22,1<<22,1<<21,1<<21)+b'\0'
V['clip2']=['set=8bim:'+H(b'8BIM\x07\xd0'+bytes([len(inner)])+inner),'clip=64x48:32x24+8+4',
            'set=8bim:'+H(res8(2000,b'')+res8(2000,knot)),'clip=64x48:32x24+8+4',
            'set=8bim:'+H(res8(2000,rec0+struct.pack('>H',1))),'clip=64x48:32x24+8+4']

def off0(e):
    n=0x4949 if e=='II' else 0x4D4D
    b=bytearray(2+12*n+6+60); b[0:2]=e.encode(); b[2:4]=P(e,'H',42); b[4:8]=P(e,'I',0)
    b[14:26]=P(e,'HHI',0x112,3,1)+S(e,1)
    return bytes(b)
def nextmul():
    e='MM'; E=65524
    ifd0=[(0x8769,4,1,L(e,E)),(0x112,3,1,S(e,1))]
    return tiff(e,{8:(ifd0,0),E:([(0x7777,4,1,L(e,1)),(0xa002,4,1,L(e,3))],0)},65600)
BIG={'off0-ii.hex':H(off0('II')),'off0-mm.hex':H(off0('MM')),'nextmul.hex':H(nextmul())}
V['exif-big']=['geom=70x50','orient=6','setfile=exif:off0-ii.hex','sync','setfile=exif:off0-mm.hex','sync','setfile=exif:nextmul.hex','sync']
FILES['exif-big']=BIG
def lvl(e,depth):
    E=400; EMPTY=380
    ifd0=[(0x8769,4,1,L(e,40)),(0x8769,4,1,L(e,E)),(0x112,3,1,S(e,1))]
    ifds={8:(ifd0,0),EMPTY:([],0)}
    o=40
    for k in range(depth):
        last=k==depth-1
        ifds[o]=([(0x8769,4,1,L(e,EMPTY if last else o+20))],(E+12 if last else 0)); o+=20
    ifds[E]=([(0x7777,4,1,L(e,0x00010000)),(0xa002,4,1,L(e,3))],0)
    return tiff(e,ifds,E+2+24+4+16)
V['exif-level']=['geom=70x50','orient=6']+sum((['set=exif:'+H(lvl('II',d)),'sync'] for d in range(1,15)),[])

V['strip']=['set=iptc:'+H(b'\x1c\x02\x05ab'),'set=icc:'+H(b'qq'),'set=xmp:'+H(b'<x/>'),'set=exif:'+H(std('II')),'strip=exif','strip=i*','strip=!xmp','strip=*']

# RemoveImageProfile of a profile that came from an 8BIM block: the profile goes, and so does
# its resource in the block (WriteTo8BimProfile with no profile)
V['remove']=['set=8bim:'+H(res8(0x7777,b'q'*20)+res8(0x404,b'\x1c\x02\x05abcd')+res8(0x7778,b'zzzz')),'remove=iptc','remove=iptc','remove=8bim','remove=8bim']

CASES = [(name, args, FILES.get(name, {})) for name, args in V.items()]
