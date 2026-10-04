/*
  imdriver: calls MagickCore functions the command line cannot reach, for the oracle.

    imdriver gradient TYPE SPREAD WxH [ARTIFACT=VALUE...] COLOR:OFFSET... OUT
    imdriver mask KIND IMAGE MASK OPERATION OUT     (KIND read|write|composite)
    imdriver getmask KIND IMAGE MASK OUT
    imdriver acquire KEY=VALUE...                   (ImageInfo fields, then AcquireImage)
    imdriver list policy|locale|mime PATTERN
    imdriver mime FILE
    imdriver pixels export|import IMAGE COLORSPACE MAP TYPE WxH+X+Y [OUT]
    imdriver linkedlist CAPACITY OP...              (append:V insert:I:V sorted:V get:I ...)
    imdriver splaytree OP...                        (add:K=V get:K delete:K remove:K ...)
    imdriver cacheview IMAGE X Y
    imdriver xml FILE|-TAG OP...                    (print child:T addchild:T:OFF content:X path:A/B:OFF ...)
    imdriver blob toblob|custom IMAGE FORMAT FRAMES [SEEKABLE] | msb BYTES | filetoimage FILE OUT

  It is linked against the build under test (build.sh), so a mutant switched on in the
  environment is active here as in magick. Output goes to stdout or to the named file.
*/
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "MagickCore/studio.h"
#include "MagickCore/MagickCore.h"
#include "MagickCore/blob-private.h"
#include "MagickCore/policy-private.h"
#include "MagickCore/utility-private.h"

static int Fail(ExceptionInfo *exception,const char *what)
{
  if (exception->severity != UndefinedException)
    (void) fprintf(stderr,"%s: %s %s\n",what,exception->reason != NULL ?
      exception->reason : "",exception->description != NULL ? exception->description : "");
  else
    (void) fprintf(stderr,"%s: failed\n",what);
  return(1);
}

static void Report(ExceptionInfo *exception)
{
  if (exception->severity != UndefinedException)
    (void) fprintf(stderr,"%d %s\n",(int) exception->severity,
      exception->reason != NULL ? exception->reason : "");
}

static Image *Read(const char *filename,ExceptionInfo *exception)
{
  ImageInfo *image_info=AcquireImageInfo();
  Image *image;
  (void) CopyMagickString(image_info->filename,filename,MagickPathExtent);
  image=ReadImage(image_info,exception);
  image_info=DestroyImageInfo(image_info);
  return(image);
}

static int Write(Image *image,const char *filename,ExceptionInfo *exception)
{
  ImageInfo *image_info=AcquireImageInfo();
  MagickBooleanType status;
  (void) CopyMagickString(image->filename,filename,MagickPathExtent);
  (void) CopyMagickString(image_info->filename,filename,MagickPathExtent);
  status=WriteImage(image_info,image,exception);
  image_info=DestroyImageInfo(image_info);
  return(status == MagickFalse ? Fail(exception,"write") : 0);
}

static int Gradient(int argc,char **argv,ExceptionInfo *exception)
{
  /* gradient TYPE SPREAD WxH COLOR:OFFSET... OUT */
  ImageInfo *image_info;
  Image *image;
  StopInfo *stops;
  size_t n,i;
  int status;
  ssize_t type,spread;
  int first;

  if (argc < 7)
    return(Fail(exception,"gradient: TYPE SPREAD WxH [ARTIFACT=VALUE...] COLOR:OFFSET... OUT"));
  type=ParseCommandOption(MagickGradientOptions,MagickFalse,argv[2]);
  if (strcmp(argv[3],"pad") == 0) spread=PadSpread;
  else if (strcmp(argv[3],"reflect") == 0) spread=ReflectSpread;
  else if (strcmp(argv[3],"repeat") == 0) spread=RepeatSpread;
  else spread=UndefinedSpread;
  image_info=AcquireImageInfo();
  (void) CloneString(&image_info->size,argv[4]);
  (void) CopyMagickString(image_info->filename,"xc:white",MagickPathExtent);
  image=ReadImage(image_info,exception);
  image_info=DestroyImageInfo(image_info);
  if (image == (Image *) NULL)
    return(Fail(exception,"gradient: canvas"));
  first=5;
  while ((first < (argc-1)) && (strchr(argv[first],'=') != NULL))
  {
    /* gradient:vector, gradient:angle, gradient:extent, gradient:center, gradient:radii */
    char key[MagickPathExtent], *value;
    (void) CopyMagickString(key,argv[first],MagickPathExtent);
    value=strchr(key,'=');
    *value++='\0';
    (void) SetImageArtifact(image,key,value);
    first++;
  }
  n=(size_t) (argc-1-first);
  stops=(StopInfo *) calloc(n,sizeof(*stops));
  for (i=0; i < n; i++)
  {
    char color[MagickPathExtent], *colon;
    (void) CopyMagickString(color,argv[first+(int) i],MagickPathExtent);
    colon=strrchr(color,':');
    stops[i].offset=colon != NULL ? strtod(colon+1,(char **) NULL) : 0.0;
    if (colon != NULL)
      *colon='\0';
    (void) QueryColorCompliance(color,AllCompliance,&stops[i].color,exception);
  }
  if (GradientImage(image,(GradientType) type,(SpreadMethod) spread,stops,n,exception) == MagickFalse)
    Report(exception);
  free(stops);
  status=Write(image,argv[argc-1],exception);
  image=DestroyImage(image);
  return(status);
}

static PixelMask MaskKind(const char *kind)
{
  if (strcmp(kind,"read") == 0) return(ReadPixelMask);
  if (strcmp(kind,"write") == 0) return(WritePixelMask);
  return(CompositePixelMask);
}

static int Mask(int argc,char **argv,ExceptionInfo *exception)
{
  /* mask KIND IMAGE MASK OPERATION OUT: set the mask, apply one operation, write */
  Image *image,*mask,*result;
  int status;

  if (argc != 7)
    return(Fail(exception,"mask: KIND IMAGE MASK OPERATION OUT"));
  image=Read(argv[3],exception);
  mask=Read(argv[4],exception);
  if ((image == (Image *) NULL) || (mask == (Image *) NULL))
    return(Fail(exception,"mask: read"));
  if (SetImageMask(image,MaskKind(argv[2]),mask,exception) == MagickFalse)
    Report(exception);
  result=(Image *) NULL;
  if (strcmp(argv[5],"negate") == 0)
    (void) NegateImage(image,MagickFalse,exception);
  else if (strcmp(argv[5],"blur") == 0)
    result=BlurImage(image,0.0,2.0,exception);
  else if (strcmp(argv[5],"composite") == 0)
    {
      Image *over=Read(argv[4],exception);
      (void) CompositeImage(image,over,OverCompositeOp,MagickTrue,5,5,exception);
      over=DestroyImage(over);
    }
  else if (strcmp(argv[5],"colorize") == 0)
    {
      PixelInfo red;
      (void) QueryColorCompliance("red",AllCompliance,&red,exception);
      result=ColorizeImage(image,"50",&red,exception);
    }
  if (result != (Image *) NULL)
    {
      image=DestroyImage(image);
      image=result;
    }
  (void) SetImageMask(image,MaskKind(argv[2]),(Image *) NULL,exception);
  status=Write(image,argv[6],exception);
  image=DestroyImage(image);
  mask=DestroyImage(mask);
  return(status);
}

static int GetMask(int argc,char **argv,ExceptionInfo *exception)
{
  /* getmask KIND IMAGE MASK OUT: set the mask, then write what GetImageMask returns */
  Image *image,*mask,*got;
  int status;

  if (argc != 6)
    return(Fail(exception,"getmask: KIND IMAGE MASK OUT"));
  image=Read(argv[3],exception);
  mask=Read(argv[4],exception);
  if ((image == (Image *) NULL) || (mask == (Image *) NULL))
    return(Fail(exception,"getmask: read"));
  (void) SetImageMask(image,MaskKind(argv[2]),mask,exception);
  got=GetImageMask(image,MaskKind(argv[2]),exception);
  if (got == (Image *) NULL)
    {
      (void) printf("no mask\n");
      status=0;
    }
  else
    {
      status=Write(got,argv[5],exception);
      got=DestroyImage(got);
    }
  image=DestroyImage(image);
  mask=DestroyImage(mask);
  return(status);
}

static int Acquire(int argc,char **argv,ExceptionInfo *exception)
{
  /* acquire KEY=VALUE...: ImageInfo fields and options, then AcquireImage and its settings */
  ImageInfo *image_info=AcquireImageInfo();
  Image *image;
  int i;

  for (i=2; i < argc; i++)
  {
    char key[MagickPathExtent], *value;
    (void) CopyMagickString(key,argv[i],MagickPathExtent);
    value=strchr(key,'=');
    if (value == NULL)
      continue;
    *value++='\0';
    if (strcmp(key,"size") == 0) (void) CloneString(&image_info->size,value);
    else if (strcmp(key,"extract") == 0) (void) CloneString(&image_info->extract,value);
    else if (strcmp(key,"page") == 0) (void) CloneString(&image_info->page,value);
    else if (strcmp(key,"density") == 0) (void) CloneString(&image_info->density,value);
    else if (strcmp(key,"depth") == 0) image_info->depth=(size_t) atol(value);
    else if (strcmp(key,"quality") == 0) image_info->quality=(size_t) atol(value);
    else if (strcmp(key,"units") == 0) image_info->units=(ResolutionType)
      ParseCommandOption(MagickResolutionOptions,MagickFalse,value);
    else if (strcmp(key,"interlace") == 0) image_info->interlace=(InterlaceType)
      ParseCommandOption(MagickInterlaceOptions,MagickFalse,value);
    else if (strcmp(key,"ping") == 0) image_info->ping=MagickTrue;
    else (void) SetImageOption(image_info,key,value);
  }
  image=AcquireImage(image_info,exception);
  Report(exception);
  (void) printf("%.20gx%.20g depth %.20g quality %.20g units %d interlace %d\n",
    (double) image->columns,(double) image->rows,(double) image->depth,
    (double) image->quality,(int) image->units,(int) image->interlace);
  (void) printf("page %.20gx%.20g%+.20g%+.20g extract %.20gx%.20g%+.20g%+.20g\n",
    (double) image->page.width,(double) image->page.height,(double) image->page.x,
    (double) image->page.y,(double) image->extract_info.width,(double) image->extract_info.height,
    (double) image->extract_info.x,(double) image->extract_info.y);
  (void) printf("resolution %.6gx%.6g ping %d dither %d\n",image->resolution.x,
    image->resolution.y,(int) image->ping,(int) image->dither);
  image=DestroyImage(image);
  image_info=DestroyImageInfo(image_info);
  return(0);
}

static int CompareStrings(const void *a,const void *b)
{
  return(strcmp(*(char * const *) a,*(char * const *) b));
}

static int List(int argc,char **argv,ExceptionInfo *exception)
{
  /* list policy|locale|mime PATTERN */
  size_t n,i;
  if (argc != 4)
    return(Fail(exception,"list: policy|locale|mime PATTERN"));
  if (strcmp(argv[2],"policy") == 0)
    {
      char **list=GetPolicyList(argv[3],&n,exception);
      for (i=0; (list != NULL) && (i < n); i++)
        { (void) printf("%s\n",list[i]); list[i]=DestroyString(list[i]); }
      if (list != NULL) list=(char **) RelinquishMagickMemory(list);
    }
  else if (strcmp(argv[2],"locale") == 0)
    {
      char **list=GetLocaleList(argv[3],&n,exception);
      for (i=0; (list != NULL) && (i < n); i++)
        { (void) printf("%s\n",list[i]); list[i]=DestroyString(list[i]); }
      if (list != NULL) list=(char **) RelinquishMagickMemory(list);
    }
  else
    {
      /* GetMimeList's order differs from run to run (entries that compare equal), so sort */
      char **list=GetMimeList(argv[3],&n,exception);
      if (list != NULL)
        qsort(list,n,sizeof(*list),CompareStrings);
      for (i=0; (list != NULL) && (i < n); i++)
        { (void) printf("%s\n",list[i]); list[i]=DestroyString(list[i]); }
      if (list != NULL) list=(char **) RelinquishMagickMemory(list);
    }
  (void) printf("%.20g\n",(double) n);
  Report(exception);
  return(0);
}

static int Mime(int argc,char **argv,ExceptionInfo *exception)
{
  /* mime FILE: GetMimeInfo on the file's name and first bytes */
  unsigned char magic[256];
  size_t length;
  const MimeInfo *info;
  FILE *file;

  if (argc != 3)
    return(Fail(exception,"mime: FILE"));
  file=fopen(argv[2],"rb");
  length=file != NULL ? fread(magic,1,sizeof(magic),file) : 0;
  if (file != NULL) (void) fclose(file);
  info=GetMimeInfo(argv[2],magic,length,exception);
  (void) printf("%s\n",info != NULL ? GetMimeType(info) : "(none)");
  (void) printf("%s\n",info != NULL ? GetMimeDescription(info) : "(none)");
  Report(exception);
  return(0);
}

/*
  Windows files (2026-10-04): pixel.c's typed Export/ImportImagePixels, the linked list and splay
  tree containers, and cache-view.c's one-pixel getters, which only the API calls.
*/
static size_t StorageSize(StorageType type)
{
  switch (type)
  {
    case CharPixel: return(sizeof(unsigned char));
    case DoublePixel: return(sizeof(double));
    case FloatPixel: return(sizeof(float));
    case LongPixel: return(sizeof(unsigned int));
    case LongLongPixel: return(sizeof(MagickSizeType));
    case QuantumPixel: return(sizeof(Quantum));
    case ShortPixel: return(sizeof(unsigned short));
    default: return(0);
  }
}

static void PrintElement(StorageType type,const void *pixels,size_t k)
{
  switch (type)
  {
    case CharPixel: (void) printf(" %u",(unsigned) ((const unsigned char *) pixels)[k]); break;
    case DoublePixel: (void) printf(" %.12g",((const double *) pixels)[k]); break;
    case FloatPixel: (void) printf(" %.7g",(double) ((const float *) pixels)[k]); break;
    case LongPixel: (void) printf(" %u",((const unsigned int *) pixels)[k]); break;
    case LongLongPixel: (void) printf(" %.20g",(double) ((const MagickSizeType *) pixels)[k]); break;
    case QuantumPixel: (void) printf(" %.7g",(double) ((const Quantum *) pixels)[k]); break;
    case ShortPixel: (void) printf(" %u",(unsigned) ((const unsigned short *) pixels)[k]); break;
    default: break;
  }
}

static void FillElement(StorageType type,void *pixels,size_t k)
{
  /* a fixed pattern per element; floating types include values below 0 and above 1 */
  double unit=(double) ((k*37+11) % 301)/256.0-0.08;
  switch (type)
  {
    case CharPixel: ((unsigned char *) pixels)[k]=(unsigned char) ((k*37+11) & 0xff); break;
    case DoublePixel: ((double *) pixels)[k]=unit; break;
    case FloatPixel: ((float *) pixels)[k]=(float) unit; break;
    case LongPixel: ((unsigned int *) pixels)[k]=(unsigned int) (k*2654435761U+12345U); break;
    case LongLongPixel: ((MagickSizeType *) pixels)[k]=(MagickSizeType) k*0x9E3779B97F4A7C15ULL+7; break;
    case QuantumPixel: ((Quantum *) pixels)[k]=(Quantum) (QuantumRange*((k*37+11) % 257)/256.0); break;
    case ShortPixel: ((unsigned short *) pixels)[k]=(unsigned short) ((k*7919+13) & 0xffff); break;
    default: break;
  }
}

static int Pixels(int argc,char **argv,ExceptionInfo *exception)
{
  /* pixels export IMAGE COLORSPACE MAP TYPE WxH+X+Y
     pixels import IMAGE COLORSPACE MAP TYPE WxH+X+Y OUT    (COLORSPACE "-" keeps the image's) */
  Image *image;
  ssize_t type, colorspace, x=0, y=0;
  size_t width=0, height=0, count, k;
  void *pixels;
  MagickBooleanType status;
  int import;

  if ((argc < 7) || ((import=(strcmp(argv[2],"import") == 0)) && (argc != 9)))
    return(Fail(exception,"pixels: export|import IMAGE COLORSPACE MAP TYPE GEOMETRY [OUT]"));
  type=ParseCommandOption(MagickStorageOptions,MagickFalse,argv[6]);
  if (type < 0)
    return(Fail(exception,"pixels: storage type"));
  image=Read(argv[3],exception);
  if (image == (Image *) NULL)
    return(Fail(exception,"read"));
  if (strcmp(argv[4],"-") != 0)
    {
      colorspace=ParseCommandOption(MagickColorspaceOptions,MagickFalse,argv[4]);
      if (colorspace >= 0)
        (void) TransformImageColorspace(image,(ColorspaceType) colorspace,exception);
    }
  (void) GetGeometry(argv[7],&x,&y,&width,&height);
  count=width*height*strlen(argv[5]);
  pixels=AcquireQuantumMemory(count+1,StorageSize((StorageType) type));
  if (pixels == (void *) NULL)
    return(Fail(exception,"memory"));
  if (import != 0)
    {
      for (k=0; k < count; k++)
        FillElement((StorageType) type,pixels,k);
      status=ImportImagePixels(image,x,y,width,height,argv[5],(StorageType) type,pixels,exception);
      (void) printf("%s\n",status != MagickFalse ? "imported" : "refused");
      Report(exception);
      status=Write(image,argv[8],exception) == 0 ? MagickTrue : MagickFalse;
    }
  else
    {
      (void) memset(pixels,0,(count+1)*StorageSize((StorageType) type));
      status=ExportImagePixels(image,x,y,width,height,argv[5],(StorageType) type,pixels,exception);
      (void) printf("%s\n",status != MagickFalse ? "exported" : "refused");
      for (k=0; (status != MagickFalse) && (k < count); k++)
        {
          PrintElement((StorageType) type,pixels,k);
          if (((k+1) % strlen(argv[5])) == 0)
            (void) printf("\n");
        }
      Report(exception);
    }
  pixels=RelinquishMagickMemory(pixels);
  image=DestroyImage(image);
  return(0);
}

/* The containers hold pointers: the same text always maps to the same pointer, so a removal by
   value finds what an earlier step stored. */
static char *interned[4096];
static size_t number_interned=0;

static const char *Intern(const char *text)
{
  size_t i;
  for (i=0; i < number_interned; i++)
    if (strcmp(interned[i],text) == 0)
      return(interned[i]);
  if (number_interned == 4096)
    return(interned[4095]);
  interned[number_interned]=ConstantString(text);
  return(interned[number_interned++]);
}

static const char *Text(const void *value)
{
  return(value != (const void *) NULL ? (const char *) value : "(null)");
}

static void *Same(void *value)
{
  return(value);
}

static void *Freed(void *value)
{
  /* a tree's relinquish function: reports, frees nothing (the strings are interned) */
  (void) printf(" freed:%s",Text(value));
  return((void *) NULL);
}

static int CompareText(const void *a,const void *b)
{
  return(strcmp((const char *) a,(const char *) b));
}

static void PrintList(LinkedListInfo *list)
{
  /* through LinkedListToArray, which leaves the list's iterator where the script put it and
     stops at the end of the chain (a middle insertion counts an element it drops) */
  size_t n=GetNumberOfElementsInLinkedList(list), i;
  void **array=(void **) AcquireQuantumMemory(n+1,sizeof(*array));
  (void) printf("  [%.20g]",(double) n);
  (void) memset(array,0,(n+1)*sizeof(*array));
  (void) LinkedListToArray(list,array);
  for (i=0; (i < n) && (array[i] != (void *) NULL); i++)
    (void) printf(" %s",Text(array[i]));
  array=(void **) RelinquishMagickMemory(array);
  (void) printf(" | empty %d last %s\n",(int) IsLinkedListEmpty(list),
    Text(GetLastValueInLinkedList(list)));
}

static int List2(int argc,char **argv,ExceptionInfo *exception)
{
  /* linkedlist CAPACITY OP... with OP one of append:V insert:I:V sorted:V get:I next remove:V
     removeat:I removelast reset array clear */
  LinkedListInfo *list;
  int i;

  if (argc < 3)
    return(Fail(exception,"linkedlist: CAPACITY OP..."));
  list=NewLinkedList((size_t) atol(argv[2]));
  for (i=3; i < argc; i++)
  {
    char *op=argv[i], *arg=strchr(op,':');
    const void *result=(const void *) NULL;
    MagickBooleanType status=MagickTrue;
    if (arg != (char *) NULL)
      *arg++='\0';
    if (strcmp(op,"append") == 0) status=AppendValueToLinkedList(list,Intern(arg));
    else if (strcmp(op,"insert") == 0)
      {
        char *value=strchr(arg,':');
        if (value != (char *) NULL) *value++='\0';
        status=InsertValueInLinkedList(list,(size_t) atol(arg),Intern(value != NULL ? value : ""));
      }
    else if (strcmp(op,"sorted") == 0)
      {
        void *replaced=(void *) NULL;
        status=InsertValueInSortedLinkedList(list,CompareText,&replaced,Intern(arg));
        result=replaced;
      }
    else if (strcmp(op,"get") == 0) result=GetValueFromLinkedList(list,(size_t) atol(arg));
    else if (strcmp(op,"next") == 0) result=GetNextValueInLinkedList(list);
    else if (strcmp(op,"remove") == 0) result=RemoveElementByValueFromLinkedList(list,Intern(arg));
    else if (strcmp(op,"removeat") == 0) result=RemoveElementFromLinkedList(list,(size_t) atol(arg));
    else if (strcmp(op,"removelast") == 0) result=RemoveLastElementFromLinkedList(list);
    else if (strcmp(op,"reset") == 0) ResetLinkedListIterator(list);
    else if (strcmp(op,"clear") == 0) ClearLinkedList(list,(void *(*)(void *)) NULL);
    else if (strcmp(op,"array") == 0)
      {
        size_t n=GetNumberOfElementsInLinkedList(list), j;
        void **array=(void **) AcquireQuantumMemory(n+1,sizeof(*array));
        status=LinkedListToArray(list,array);
        (void) printf("%s array", status != MagickFalse ? "ok" : "fail");
        for (j=0; (status != MagickFalse) && (j < n); j++)
          (void) printf(" %s",Text(array[j]));
        (void) printf("\n");
        array=(void **) RelinquishMagickMemory(array);
      }
    else { (void) fprintf(stderr,"unknown op %s\n",op); continue; }
    (void) printf("%s%s%s -> %d %s\n",op,arg != NULL ? " " : "",arg != NULL ? arg : "",
      (int) status,Text(result));
    if ((strcmp(op,"next") != 0) && (strcmp(op,"reset") != 0))
      PrintList(list);
  }
  list=DestroyLinkedList(list,(void *(*)(void *)) NULL);
  return(0);
}

static int int_keys=0;  /* splaytree mode:int: keys are small integers, compared as pointers */

static const void *Key(const char *text)
{
  return(int_keys != 0 ? (const void *) (size_t) (atol(text)+1) : (const void *) Intern(text));
}

static const void *Lookup(const char *text)
{
  /* a key to look up: a fresh copy of the text, so only a comparison by content finds it */
  return(int_keys != 0 ? Key(text) : (const void *) ConstantString(text));
}

static const char *KeyText(const void *key)
{
  static char text[32];
  if (int_keys == 0)
    return(Text(key));
  (void) FormatLocaleString(text,sizeof(text),"%ld",(long) ((size_t) key)-1);
  return(text);
}

static void *FreedKey(void *key)
{
  (void) printf(" freedkey:%s",KeyText(key));
  return((void *) NULL);
}

static void PrintTree(SplayTreeInfo *tree)
{
  const void *key;
  (void) printf("  {%.20g}",(double) GetNumberOfNodesInSplayTree(tree));
  ResetSplayTreeIterator(tree);
  while ((key=GetNextKeyInSplayTree(tree)) != (const void *) NULL)
    (void) printf(" %s=%s",KeyText(key),Text(GetValueFromSplayTree(tree,key)));
  (void) printf(" | root %s\n",Text(GetRootValueFromSplayTree(tree)));
}

static int Tree(int argc,char **argv,ExceptionInfo *exception)
{
  /* splaytree OP... with OP one of add:K=V get:K delete:K deletevalue:V removevalue:V remove:K
     values reset clone; addrange:N adds k0000=v0000 ... in ascending order (a chain deep enough
     for the tree to balance itself past depth 1024), quiet and loud stop and resume printing */
  SplayTreeInfo *tree;
  int i, loud=1;

  i=2;
  if ((argc > 2) && (strncmp(argv[2],"mode:",5) == 0))
    {
      /* mode:free gives the tree relinquish functions; mode:pointer compares keys by address
         (the order of the interned strings), mode:freepointer both */
      const char *mode=argv[2]+5;
      int_keys=strstr(mode,"int") != NULL ? 1 : 0;
      tree=NewSplayTree((strstr(mode,"pointer") != NULL) || (int_keys != 0) ?
        (int (*)(const void *,const void *)) NULL : CompareSplayTreeString,
        strstr(mode,"free") != NULL ? FreedKey : (void *(*)(void *)) NULL,
        strstr(mode,"free") != NULL ? Freed : (void *(*)(void *)) NULL);
      i=3;
    }
  else
    tree=NewSplayTree(CompareSplayTreeString,(void *(*)(void *)) NULL,(void *(*)(void *)) NULL);
  for ( ; i < argc; i++)
  {
    char *op=argv[i], *arg=strchr(op,':');
    const void *result=(const void *) NULL;
    MagickBooleanType status=MagickTrue;
    if (arg != (char *) NULL)
      *arg++='\0';
    if (strcmp(op,"add") == 0)
      {
        char *value=strchr(arg,'=');
        if (value != (char *) NULL) *value++='\0';
        status=AddValueToSplayTree(tree,Key(arg),Intern(value != NULL ? value : ""));
      }
    else if (strcmp(op,"get") == 0) result=GetValueFromSplayTree(tree,Lookup(arg));
    else if (strcmp(op,"delete") == 0) status=DeleteNodeFromSplayTree(tree,Lookup(arg));
    else if (strcmp(op,"deletevalue") == 0) status=DeleteNodeByValueFromSplayTree(tree,Intern(arg));
    else if (strcmp(op,"removevalue") == 0)
      {
        const void *key=RemoveNodeByValueFromSplayTree(tree,Intern(arg));
        (void) printf("key %s\n",key != (const void *) NULL ? KeyText(key) : "(null)");
      }
    else if (strcmp(op,"remove") == 0) result=RemoveNodeFromSplayTree(tree,Lookup(arg));
    else if (strcmp(op,"reset") == 0) ResetSplayTree(tree);
    else if (strcmp(op,"quiet") == 0) { loud=0; continue; }
    else if (strcmp(op,"loud") == 0) { loud=1; continue; }
    else if (strcmp(op,"addrange") == 0)
      {
        long j, n=atol(arg);
        char key[16], value[16];
        for (j=0; j < n; j++)
        {
          (void) FormatLocaleString(key,sizeof(key),int_keys != 0 ? "%ld" : "k%04ld",j);
          (void) FormatLocaleString(value,sizeof(value),"v%04ld",j);
          status=AddValueToSplayTree(tree,Key(key),Intern(value));
        }
      }
    else if (strcmp(op,"values") == 0)
      {
        const void *value;
        ResetSplayTreeIterator(tree);
        (void) printf("values");
        while ((value=GetNextValueInSplayTree(tree)) != (const void *) NULL)
          (void) printf(" %s",Text(value));
        (void) printf("\n");
      }
    else if (strcmp(op,"clone") == 0)
      {
        SplayTreeInfo *clone=CloneSplayTree(tree,Same,Same);
        (void) printf("clone");
        PrintTree(clone);
        clone=DestroySplayTree(clone);
      }
    else { (void) fprintf(stderr,"unknown op %s\n",op); continue; }
    (void) printf("%s%s%s -> %d %s\n",op,arg != NULL ? " " : "",arg != NULL ? arg : "",
      (int) status,Text(result));
    if (loud != 0)
      PrintTree(tree);
  }
  tree=DestroySplayTree(tree);
  return(0);
}

static void PrintQuanta(const Image *image,const Quantum *q)
{
  ssize_t i;
  for (i=0; i < (ssize_t) GetPixelChannels(image); i++)
    (void) printf(" %.7g",(double) q[i]);
  (void) printf("\n");
}

static int View(int argc,char **argv,ExceptionInfo *exception)
{
  /* cacheview IMAGE X Y: the one-pixel getters of cache-view.c, at (X,Y), with each virtual
     pixel method, through a clone, and the view's colorspace and class */
  Image *image;
  CacheView *view, *clone;
  Quantum q[MaxPixelChannels];
  PixelInfo info;
  ssize_t x, y, method;
  MagickBooleanType status;

  if (argc != 5)
    return(Fail(exception,"cacheview: IMAGE X Y"));
  image=Read(argv[2],exception);
  if (image == (Image *) NULL)
    return(Fail(exception,"read"));
  x=(ssize_t) atol(argv[3]);
  y=(ssize_t) atol(argv[4]);
  view=AcquireVirtualCacheView(image,exception);
  (void) memset(q,0,sizeof(q));
  status=GetOneCacheViewVirtualPixel(view,x,y,q,exception);
  (void) printf("virtual %d",(int) status); PrintQuanta(image,q);
  for (method=0; method <= (ssize_t) CheckerTileVirtualPixelMethod; method++)
  {
    if (method == (ssize_t) RandomVirtualPixelMethod)
      continue;  /* differs from run to run */
    (void) memset(q,0,sizeof(q));
    status=GetOneCacheViewVirtualMethodPixel(view,(VirtualPixelMethod) method,x,y,q,exception);
    (void) printf("method %s %d",CommandOptionToMnemonic(MagickVirtualPixelOptions,method),
      (int) status);
    PrintQuanta(image,q);
  }
  (void) memset(&info,0,sizeof(info));  /* GetOneCacheViewVirtualPixelInfo must fill it in */
  status=GetOneCacheViewVirtualPixelInfo(view,x,y,&info,exception);
  (void) printf("info %d %.7g %.7g %.7g %.7g %.7g %s depth %.20g fuzz %.7g alpha %d\n",(int) status,
    (double) info.red,(double) info.green,(double) info.blue,(double) info.black,(double) info.alpha,
    CommandOptionToMnemonic(MagickColorspaceOptions,(ssize_t) info.colorspace),(double) info.depth,
    info.fuzz,(int) info.alpha_trait);
  clone=CloneCacheView(view);
  (void) memset(q,0,sizeof(q));
  status=GetOneCacheViewVirtualPixel(clone,x,y,q,exception);
  (void) printf("clone %d",(int) status); PrintQuanta(image,q);
  (void) printf("colorspace %s class %s image %.20gx%.20g\n",
    CommandOptionToMnemonic(MagickColorspaceOptions,(ssize_t) GetCacheViewColorspace(clone)),
    CommandOptionToMnemonic(MagickClassOptions,(ssize_t) GetCacheViewStorageClass(clone)),
    (double) GetCacheViewImage(clone)->columns,(double) GetCacheViewImage(clone)->rows);
  clone=DestroyCacheView(clone);
  view=DestroyCacheView(view);
  view=AcquireAuthenticCacheView(image,exception);
  (void) memset(q,0,sizeof(q));
  status=GetOneCacheViewAuthenticPixel(view,x,y,q,exception);
  (void) printf("authentic %d",(int) status); PrintQuanta(image,q);
  status=SetCacheViewStorageClass(view,PseudoClass,exception);
  (void) printf("set PseudoClass %d: %s, %.20g colours\n",(int) status,
    CommandOptionToMnemonic(MagickClassOptions,(ssize_t) GetCacheViewStorageClass(view)),
    (double) image->colors);
  view=DestroyCacheView(view);
  Report(exception);
  image=DestroyImage(image);
  return(0);
}

/* xml-tree.c: MagickPrivate, declared here (the driver links the static library) */
extern XMLTreeInfo *AddPathToXMLTree(XMLTreeInfo *,const char *,const size_t);

static void PrintNode(const char *what,XMLTreeInfo *node)
{
  (void) printf("%s %s",what,node != (XMLTreeInfo *) NULL ? Text(GetXMLTreeTag(node)) : "(none)");
  if (node != (XMLTreeInfo *) NULL)
    (void) printf(" [%s]",Text(GetXMLTreeContent(node)));
  (void) printf("\n");
}

static int Xml(int argc,char **argv,ExceptionInfo *exception)
{
  /* xml FILE|-TAG OP... : parse FILE (or start a tree with NewXMLTreeTag(TAG)), then
     print child:T sibling next top attr:N addchild:T:OFFSET content:TEXT path:A/B:OFFSET */
  XMLTreeInfo *top, *cur;
  int i;

  if (argc < 3)
    return(Fail(exception,"xml: FILE|-TAG OP..."));
  if (*argv[2] == '-')
    top=NewXMLTreeTag(argv[2]+1);
  else
    {
      char *text=FileToString(argv[2],~0UL,exception);
      if (text == (char *) NULL)
        return(Fail(exception,"read"));
      top=NewXMLTree(text,exception);
      text=DestroyString(text);
    }
  Report(exception);
  if (top == (XMLTreeInfo *) NULL)
    {
      (void) printf("no tree\n");
      return(0);
    }
  cur=top;
  for (i=3; i < argc; i++)
  {
    char *op=argv[i], *arg=strchr(op,':');
    if (arg != (char *) NULL)
      *arg++='\0';
    if (strcmp(op,"print") == 0)
      {
        char *xml=XMLTreeInfoToXML(top);
        (void) printf("%s\n",xml != (char *) NULL ? xml : "(null)");
        if (xml != (char *) NULL) xml=DestroyString(xml);
        continue;
      }
    if (strcmp(op,"child") == 0) cur=GetXMLTreeChild(cur,arg);
    else if (strcmp(op,"sibling") == 0) cur=GetXMLTreeSibling(cur);
    else if (strcmp(op,"next") == 0) cur=GetNextXMLTreeTag(cur);
    else if (strcmp(op,"top") == 0) cur=top;
    else if (strcmp(op,"attr") == 0)
      {
        (void) printf("attr %s = %s\n",arg,Text(GetXMLTreeAttribute(cur,arg)));
        continue;
      }
    else if (strcmp(op,"addchild") == 0)
      {
        char *offset=strchr(arg,':');
        if (offset != (char *) NULL) *offset++='\0';
        cur=AddChildToXMLTree(cur,arg,offset != NULL ? (size_t) atol(offset) : 0);
      }
    else if (strcmp(op,"content") == 0) cur=SetXMLTreeContent(cur,arg);
    else if (strcmp(op,"path") == 0)
      {
        char *offset=strrchr(arg,':');
        if (offset != (char *) NULL) *offset++='\0';
        cur=AddPathToXMLTree(top,arg,offset != NULL ? (size_t) atol(offset) : 0);
      }
    else { (void) fprintf(stderr,"unknown op %s\n",op); continue; }
    PrintNode(op,cur);
    if (cur == (XMLTreeInfo *) NULL)
      cur=top;
  }
  top=DestroyXMLTree(top);
  return(0);
}

/* blob.c: blobs, custom streams over a memory buffer, byte order, FileToImage */
typedef struct _MemoryStream
{
  unsigned char *data;
  size_t length, extent;
  MagickOffsetType offset;
  int seekable;
} MemoryStream;

static ssize_t StreamWrite(unsigned char *data,const size_t count,void *user)
{
  MemoryStream *s=(MemoryStream *) user;
  if ((size_t) s->offset+count > s->extent)
    {
      s->extent=2*((size_t) s->offset+count);
      s->data=(unsigned char *) ResizeQuantumMemory(s->data,s->extent,1);
    }
  (void) memcpy(s->data+s->offset,data,count);
  s->offset+=(MagickOffsetType) count;
  if ((size_t) s->offset > s->length)
    s->length=(size_t) s->offset;
  return((ssize_t) count);
}

static ssize_t StreamRead(unsigned char *data,const size_t count,void *user)
{
  MemoryStream *s=(MemoryStream *) user;
  size_t n=count;
  if ((size_t) s->offset >= s->length)
    return(0);
  if ((size_t) s->offset+n > s->length)
    n=s->length-(size_t) s->offset;
  (void) memcpy(data,s->data+s->offset,n);
  s->offset+=(MagickOffsetType) n;
  return((ssize_t) n);
}

static MagickOffsetType StreamSeek(const MagickOffsetType offset,const int whence,void *user)
{
  MemoryStream *s=(MemoryStream *) user;
  MagickOffsetType o=offset;
  if (whence == SEEK_CUR) o+=s->offset;
  if (whence == SEEK_END) o+=(MagickOffsetType) s->length;
  if (o < 0)
    return(-1);
  s->offset=o;
  return(o);
}

static MagickOffsetType StreamTell(void *user)
{
  return(((MemoryStream *) user)->offset);
}

static unsigned long Fnv(const unsigned char *p,size_t n)
{
  unsigned long h=2166136261UL;
  size_t i;
  for (i=0; i < n; i++)
    h=((h ^ p[i])*16777619UL) & 0xffffffffUL;
  return(h);
}

static void Describe(const char *what,Image *image,ExceptionInfo *exception)
{
  Image *p;
  if (image == (Image *) NULL)
    {
      (void) printf("%s: no image\n",what);
      return;
    }
  for (p=image; p != (Image *) NULL; p=GetNextImageInList(p))
  {
    (void) SignatureImage(p,exception);
    (void) printf("%s: %s %.20gx%.20g %s\n",what,p->magick,(double) p->columns,(double) p->rows,
      GetImageProperty(p,"signature",exception));
  }
}

static int Blob(int argc,char **argv,ExceptionInfo *exception)
{
  /* blob toblob IMAGE FORMAT FRAMES          ImageToBlob/ImagesToBlob, BlobToImage, PingBlob
     blob custom IMAGE FORMAT FRAMES SEEKABLE ImageToCustomStream/ImagesToCustomStream, CustomStreamToImage
     blob msb BYTES                           MSBOrderLong and MSBOrderShort of 0..BYTES-1
     blob filetoimage FILE OUT                FileToImage into OUT's blob */
  ImageInfo *image_info;
  Image *image, *images;
  size_t length=0, frames, i;
  void *blob;

  if ((argc >= 4) && (strcmp(argv[2],"msb") == 0))
    {
      unsigned char bytes[64];
      size_t n=(size_t) atol(argv[3]) % 64;
      (void) memset(bytes,0,sizeof(bytes));  /* a length not a multiple of 4 reads past it */
      for (i=0; i < n; i++) bytes[i]=(unsigned char) i;
      MSBOrderLong(bytes,n);
      for (i=0; i < n; i++) (void) printf(" %u",(unsigned) bytes[i]);
      (void) printf("\n");
      MSBOrderShort(bytes,n);
      for (i=0; i < n; i++) (void) printf(" %u",(unsigned) bytes[i]);
      (void) printf("\n");
      return(0);
    }
  if ((argc == 5) && (strcmp(argv[2],"filetoimage") == 0))
    {
      MagickBooleanType status;
      image_info=AcquireImageInfo();
      image=AcquireImage(image_info,exception);
      (void) CopyMagickString(image->filename,argv[4],MagickPathExtent);
      status=OpenBlob(image_info,image,WriteBinaryBlobMode,exception);
      if (status != MagickFalse)
        {
          status=FileToImage(image,argv[3],exception);
          (void) printf("filetoimage %d tell %.20g\n",(int) status,(double) TellBlob(image));
          (void) CloseBlob(image);
        }
      Report(exception);
      image=DestroyImage(image);
      image_info=DestroyImageInfo(image_info);
      return(0);
    }
  if (argc < 6)
    return(Fail(exception,"blob: toblob|custom IMAGE FORMAT FRAMES [SEEKABLE]"));
  image=Read(argv[3],exception);
  if (image == (Image *) NULL)
    return(Fail(exception,"read"));
  frames=(size_t) atol(argv[5]);
  images=NewImageList();
  for (i=0; i < frames; i++)
    AppendImageToList(&images,CloneImage(image,0,0,MagickTrue,exception));
  image=DestroyImage(image);
  image_info=AcquireImageInfo();
  (void) CopyMagickString(image_info->magick,argv[4],MagickPathExtent);
  (void) FormatLocaleString(image_info->filename,MagickPathExtent,"%s:",argv[4]);
  if (strcmp(argv[2],"toblob") == 0)
    {
      Image *back;
      blob=frames > 1 ? ImagesToBlob(image_info,images,&length,exception) :
        ImageToBlob(image_info,images,&length,exception);
      (void) printf("blob %.20g bytes %08lx\n",(double) length,
        blob != NULL ? Fnv((const unsigned char *) blob,length) : 0UL);
      Report(exception);
      if (blob != (void *) NULL)
        {
          back=BlobToImage(image_info,blob,length,exception);
          Describe("back",back,exception);
          if (back != (Image *) NULL) back=DestroyImageList(back);
          back=PingBlob(image_info,blob,length,exception);
          if (back != (Image *) NULL)
            (void) printf("ping: %.20gx%.20g\n",(double) back->columns,(double) back->rows);
          if (back != (Image *) NULL) back=DestroyImageList(back);
          blob=RelinquishMagickMemory(blob);
        }
    }
  else
    {
      MemoryStream s;
      CustomStreamInfo *custom=AcquireCustomStreamInfo(exception);
      Image *back;
      (void) memset(&s,0,sizeof(s));
      s.seekable=argc > 6 ? atoi(argv[6]) : 1;
      SetCustomStreamData(custom,&s);
      SetCustomStreamWriter(custom,StreamWrite);
      SetCustomStreamReader(custom,StreamRead);
      if (s.seekable != 0)
        {
          SetCustomStreamSeeker(custom,StreamSeek);
          SetCustomStreamTeller(custom,StreamTell);
        }
      image_info->custom_stream=custom;
      *image_info->filename='\0';  /* the format comes from magick; CustomStreamToImage prefixes it */
      if (frames > 1)
        ImagesToCustomStream(image_info,images,exception);
      else
        ImageToCustomStream(image_info,images,exception);
      (void) printf("stream %.20g bytes %08lx\n",(double) s.length,s.data != NULL ? Fnv(s.data,s.length) : 0UL);
      Report(exception);
      s.offset=0;
      back=CustomStreamToImage(image_info,exception);
      Describe("back",back,exception);
      if (back != (Image *) NULL) back=DestroyImageList(back);
      image_info->custom_stream=(CustomStreamInfo *) NULL;
      custom=DestroyCustomStreamInfo(custom);
      if (s.data != NULL) s.data=(unsigned char *) RelinquishMagickMemory(s.data);
    }
  Report(exception);
  images=DestroyImageList(images);
  image_info=DestroyImageInfo(image_info);
  return(0);
}

/* quantum-import.c, quantum-export.c: ImportQuantumPixels and ExportQuantumPixels per row */
static const struct { const char *name; QuantumType type; } quantum_types[] = {
  { "alpha", AlphaQuantum }, { "bgra", BGRAQuantum }, { "bgro", BGROQuantum }, { "bgr", BGRQuantum },
  { "black", BlackQuantum }, { "blue", BlueQuantum }, { "cbycra", CbYCrAQuantum },
  { "cbycr", CbYCrQuantum }, { "cbycry", CbYCrYQuantum }, { "cmyka", CMYKAQuantum },
  { "cmyko", CMYKOQuantum }, { "cmyk", CMYKQuantum }, { "cyan", CyanQuantum },
  { "grayalpha", GrayAlphaQuantum }, { "gray", GrayQuantum }, { "green", GreenQuantum },
  { "indexalpha", IndexAlphaQuantum }, { "index", IndexQuantum }, { "magenta", MagentaQuantum },
  { "opacity", OpacityQuantum }, { "red", RedQuantum }, { "rgba", RGBAQuantum },
  { "rgbo", RGBOQuantum }, { "rgbpad", RGBPadQuantum }, { "rgb", RGBQuantum },
  { "yellow", YellowQuantum }, { "multispectral", MultispectralQuantum }, { NULL, UndefinedQuantum } };

static QuantumInfo *SetupQuantum(const ImageInfo *image_info,Image *image,char **argv,int argc,
  int first)
{
  /* argv[first..]: DEPTH FORMAT ENDIAN [pack] [minwhite] [pad=N] [scale=X] [alpha=TYPE] */
  QuantumInfo *quantum_info;
  ssize_t format=ParseCommandOption(MagickQuantumFormatOptions,MagickFalse,argv[first+1]);
  ssize_t endian=ParseCommandOption(MagickEndianOptions,MagickFalse,argv[first+2]);
  int i;
  for (i=first+3; i < argc; i++)  /* an alpha channel for a palette image, before the QuantumInfo */
    if ((strcmp(argv[i],"alpha") == 0) && (image->alpha_trait == UndefinedPixelTrait))
      {
        ExceptionInfo *sans=AcquireExceptionInfo();
        (void) SetImageAlphaChannel(image,OpaqueAlphaChannel,sans);
        sans=DestroyExceptionInfo(sans);
      }
  for (i=first+3; i < argc; i++)  /* meta channels first: the QuantumInfo is sized for them */
    if ((strncmp(argv[i],"meta=",5) == 0) && (image->number_meta_channels != (size_t) atol(argv[i]+5)))
      {
        ExceptionInfo *sans=AcquireExceptionInfo();
        ssize_t x, y, j;
        (void) SetPixelMetaChannels(image,(size_t) atol(argv[i]+5),sans);
        for (y=0; y < (ssize_t) image->rows; y++)  /* the new channels start uninitialised */
        {
          Quantum *q=GetAuthenticPixels(image,0,y,image->columns,1,sans);
          if (q == (Quantum *) NULL)
            break;
          for (x=0; x < (ssize_t) image->columns; x++)
          {
            for (j=0; j < (ssize_t) image->number_meta_channels; j++)
              q[GetPixelChannelOffset(image,(PixelChannel) (MetaPixelChannels+j))]=
                (Quantum) (GetPixelRed(image,q)/(j+2));
            q+=GetPixelChannels(image);
          }
          (void) SyncAuthenticPixels(image,sans);
        }
        sans=DestroyExceptionInfo(sans);
      }
  quantum_info=AcquireQuantumInfo(image_info,image);
  if (format >= 0)
    (void) SetQuantumFormat(image,quantum_info,(QuantumFormatType) format);
  (void) SetQuantumDepth(image,quantum_info,(size_t) atol(argv[first]));
  if (endian >= 0)
    (void) SetQuantumEndian(image,quantum_info,(EndianType) endian);
  for (i=first+3; i < argc; i++)
  {
    if (strcmp(argv[i],"pack") == 0) SetQuantumPack(quantum_info,MagickTrue);
    else if (strcmp(argv[i],"nopack") == 0) SetQuantumPack(quantum_info,MagickFalse);
    else if (strcmp(argv[i],"minwhite") == 0) SetQuantumMinIsWhite(quantum_info,MagickTrue);
    else if (strncmp(argv[i],"pad=",4) == 0)
      (void) printf("pad %s: %d\n",argv[i]+4,(int) SetQuantumPad(image,quantum_info,
        (size_t) strtoull(argv[i]+4,(char **) NULL,10)));
    else if (strncmp(argv[i],"metachannel=",12) == 0)
      (void) printf("metachannel %s: %d\n",argv[i]+12,(int) SetQuantumMetaChannel(image,quantum_info,
        (ssize_t) atol(argv[i]+12)));
    else if (strncmp(argv[i],"scale=",6) == 0) SetQuantumScale(quantum_info,atof(argv[i]+6));
    else if (strncmp(argv[i],"quantum=",8) == 0) SetQuantumQuantum(quantum_info,(size_t) atol(argv[i]+8));
    else if (strcmp(argv[i],"disassociated") == 0) SetQuantumAlphaType(quantum_info,DisassociatedQuantumAlpha);
  }
  return(quantum_info);
}

static int QuantumCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* quantum export IMAGE TYPE DEPTH FORMAT ENDIAN [opts]          print each row's bytes
     quantum roundtrip IMAGE TYPE DEPTH FORMAT ENDIAN OUT [opts]   export, import into a clone
     quantum import IMAGE TYPE DEPTH FORMAT ENDIAN OUT [opts]      import a byte pattern
     The first 3 rows of IMAGE. */
  ImageInfo *image_info;
  Image *image, *target=(Image *) NULL;
  QuantumInfo *quantum_info, *target_info=(QuantumInfo *) NULL;
  QuantumType type=UndefinedQuantum;
  unsigned char *pixels;
  size_t extent, n, rows, k;
  ssize_t y;
  int i, mode, first;

  if (argc < 8)
    return(Fail(exception,"quantum: export|roundtrip|import IMAGE TYPE DEPTH FORMAT ENDIAN [OUT] [opts]"));
  mode=strcmp(argv[2],"export") == 0 ? 0 : strcmp(argv[2],"roundtrip") == 0 ? 1 : 2;
  for (i=0; quantum_types[i].name != NULL; i++)
    if (strcmp(quantum_types[i].name,argv[4]) == 0)
      type=quantum_types[i].type;
  image=Read(argv[3],exception);
  if (image == (Image *) NULL)
    return(Fail(exception,"read"));
  image_info=AcquireImageInfo();
  first=5;
  quantum_info=SetupQuantum(image_info,image,argv,argc,first);
  extent=GetQuantumExtent(image,quantum_info,type);
  (void) printf("type %s depth %.20g extent %.20g\n",argv[4],(double) atol(argv[5]),(double) extent);
  pixels=GetQuantumPixels(quantum_info);  /* the buffer the library sizes for itself, as the coders use it */
  rows=image->rows < 3 ? image->rows : 3;
  if (mode != 0)
    {
      target=CloneImage(image,0,0,MagickTrue,exception);
      target_info=SetupQuantum(image_info,target,argv,argc,first);
      for (y=0; y < (ssize_t) target->rows; y++)  /* blank, so a skipped import shows */
      {
        Quantum *q=GetAuthenticPixels(target,0,y,target->columns,1,exception);
        if (q == (Quantum *) NULL)
          break;
        (void) memset(q,0,target->columns*GetPixelChannels(target)*sizeof(*q));
        (void) SyncAuthenticPixels(target,exception);
      }
    }
  for (y=0; y < (ssize_t) rows; y++)
  {
    (void) memset(pixels,0,extent);
    if (mode == 2)
      for (k=0; k < extent; k++)
        pixels[k]=(unsigned char) ((k*37+11+(size_t) y*101) & 0xff);
    else
      {
        if (GetVirtualPixels(image,0,y,image->columns,1,exception) == (const Quantum *) NULL)
          break;
        n=ExportQuantumPixels(image,(CacheView *) NULL,quantum_info,type,pixels,exception);
        (void) printf("row %.20g: %.20g bytes %08lx\n",(double) y,(double) n,Fnv(pixels,n));
      }
    if (mode != 0)
      {
        if (QueueAuthenticPixels(target,0,y,target->columns,1,exception) == (Quantum *) NULL)
          break;
        n=ImportQuantumPixels(target,(CacheView *) NULL,target_info,type,pixels,exception);
        (void) SyncAuthenticPixels(target,exception);
        (void) printf("import row %.20g: %.20g bytes\n",(double) y,(double) n);
      }
  }
  Report(exception);
  if (target != (Image *) NULL)
    {
      Image *crop;
      RectangleInfo geometry={ target->columns, rows, 0, 0 };
      crop=CropImage(target,&geometry,exception);
      if (crop != (Image *) NULL)
        {
          (void) Write(crop,argv[8],exception);
          crop=DestroyImage(crop);
        }
      target_info=DestroyQuantumInfo(target_info);
      target=DestroyImage(target);
    }
  pixels=(unsigned char *) NULL;
  quantum_info=DestroyQuantumInfo(quantum_info);
  image_info=DestroyImageInfo(image_info);
  image=DestroyImage(image);
  return(0);
}

/* matrix.c: MatrixInfo in memory, mapped and on disk; the least-squares helpers */
extern MagickBooleanType GaussJordanElimination(double **,double **,const size_t,const size_t);
extern void LeastSquaresAddTerms(double **,double **,const double *,const double *,const size_t,
  const size_t);

static int MatrixCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* matrix info W H memory|map|disk     fill, read back in and out of range, NullMatrix,
                                         MatrixToImage
     matrix gauss N KIND [VECTORS]       KIND regular|singular|pivot|lsq */
  if ((argc >= 6) && (strcmp(argv[2],"info") == 0))
    {
      size_t columns=(size_t) atol(argv[3]), rows=(size_t) atol(argv[4]);
      MatrixInfo *matrix;
      ssize_t x, y;
      double value;
      Image *image;
      if (strcmp(argv[5],"disk") == 0)
        {
          (void) SetMagickResourceLimit(MemoryResource,0);
          (void) SetMagickResourceLimit(MapResource,0);
        }
      if (strcmp(argv[5],"disksync") == 0)  /* AcquireMatrixInfo reads MAGICK_SYNCHRONIZE */
        {
          (void) setenv("MAGICK_SYNCHRONIZE","true",1);
          (void) SetMagickResourceLimit(MemoryResource,0);
          (void) SetMagickResourceLimit(MapResource,0);
        }
      else if (strcmp(argv[5],"map") == 0)
        (void) SetMagickResourceLimit(MemoryResource,0);
      matrix=AcquireMatrixInfo(columns,rows,sizeof(double),exception);
      Report(exception);
      if (matrix == (MatrixInfo *) NULL)
        {
          (void) printf("no matrix\n");
          return(0);
        }
      (void) printf("matrix %.20gx%.20g\n",(double) GetMatrixColumns(matrix),(double) GetMatrixRows(matrix));
      for (y=0; y < (ssize_t) rows; y++)
        for (x=0; x < (ssize_t) columns; x++)
        {
          value=7.5*x-3.25*y+(x == y ? 100.0 : 0.0);
          if (SetMatrixElement(matrix,x,y,&value) == MagickFalse)
            (void) printf("set %.20g,%.20g failed\n",(double) x,(double) y);
        }
      for (y=-1; y <= (ssize_t) rows; y++)
      {
        for (x=-1; x <= (ssize_t) columns; x++)
        {
          value=-999.0;
          (void) printf(" %d:%.6g",(int) GetMatrixElement(matrix,x,y,&value),value);
        }
        (void) printf("\n");
      }
      value=1.0;
      (void) printf("set outside: %d %d %d %d\n",(int) SetMatrixElement(matrix,-1,0,&value),
        (int) SetMatrixElement(matrix,(ssize_t) columns,0,&value),
        (int) SetMatrixElement(matrix,0,-1,&value),(int) SetMatrixElement(matrix,0,(ssize_t) rows,&value));
      image=MatrixToImage(matrix,exception);
      Describe("image",image,exception);
      if (image != (Image *) NULL) image=DestroyImage(image);
      (void) printf("null %d\n",(int) NullMatrix(matrix));
      value=-1.0;
      (void) GetMatrixElement(matrix,(ssize_t) columns/2,(ssize_t) rows/2,&value);
      (void) printf("after null %.6g\n",value);
      image=MatrixToImage(matrix,exception);
      Describe("null image",image,exception);
      if (image != (Image *) NULL) image=DestroyImage(image);
      Report(exception);
      (void) printf("resources held: memory %.20g map %.20g disk %.20g\n",
        (double) GetMagickResource(MemoryResource),(double) GetMagickResource(MapResource),
        (double) GetMagickResource(DiskResource));
      matrix=DestroyMatrixInfo(matrix);
      (void) printf("resources after: memory %.20g map %.20g disk %.20g\n",
        (double) GetMagickResource(MemoryResource),(double) GetMagickResource(MapResource),
        (double) GetMagickResource(DiskResource));
      return(0);
    }
  if ((argc >= 5) && (strcmp(argv[2],"gauss") == 0))
    {
      size_t n=(size_t) atol(argv[3]), vectors=argc > 5 ? (size_t) atol(argv[5]) : 1, i, j;
      double **matrix=AcquireMagickMatrix(n,n), **v=AcquireMagickMatrix(vectors,n);
      MagickBooleanType status;
      if ((matrix == (double **) NULL) || (v == (double **) NULL))
        {
          (void) printf("no matrix\n");
          return(0);
        }
      for (i=0; i < n; i++)
        for (j=0; j < n; j++)
          matrix[i][j]=(i == j ? 10.0+i : 1.0/(1.0+i+2.0*j));
      if (strcmp(argv[4],"singular") == 0)
        for (j=0; j < n; j++) matrix[n-1][j]=2.0*matrix[0][j];
      if (strcmp(argv[4],"zero") == 0)  /* rank 2 exactly: a zero pivot, no rounding to hide it */
        for (i=0; i < n; i++) for (j=0; j < n; j++) matrix[i][j]=(double) (i+j);
      if (strcmp(argv[4],"pivot") == 0)
        for (i=0; i < n; i++) matrix[i][i]=(i % 2 == 0) ? 0.0 : 0.001*(i+1);
      for (i=0; i < vectors; i++)
        for (j=0; j < n; j++)
          v[i][j]=1.0+i-0.5*j;
      if (strcmp(argv[4],"lsq") == 0)
        {
          /* fit a line through points with LeastSquaresAddTerms, as the distortions do */
          double terms[16], results[4];
          size_t k;
          for (i=0; i < n; i++) { for (j=0; j < n; j++) matrix[i][j]=0.0; }
          for (i=0; i < vectors; i++) for (j=0; j < n; j++) v[i][j]=0.0;
          for (k=0; k < 12; k++)
          {
            for (j=0; j < n; j++) terms[j]=pow((double) k,(double) j);
            for (i=0; i < vectors; i++) results[i]=3.0+2.0*k-0.25*k*k+i;
            LeastSquaresAddTerms(matrix,v,terms,results,n,vectors);
          }
        }
      status=GaussJordanElimination(matrix,v,n,vectors);
      (void) printf("gauss %d\n",(int) status);
      for (i=0; i < vectors; i++)
      {
        for (j=0; j < n; j++)
          (void) printf(" %.9g",v[i][j]);
        (void) printf("\n");
      }
      matrix=RelinquishMagickMatrix(matrix,n);
      v=RelinquishMagickMatrix(v,vectors);
      return(0);
    }
  return(Fail(exception,"matrix: info W H memory|map|disk | gauss N regular|singular|pivot|lsq [VECTORS]"));
}

/* resample.c: ResamplePixelColor on a grid around and across the image's edges */
static int ResampleCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* resample IMAGE VIRTUAL-PIXEL FILTER SCALE [interpolate=METHOD]: an elliptical sample at
     u,v in steps of 0.5 from -8 to the size+8, the ellipse scaled by SCALE (0 = point) */
  Image *image;
  ResampleFilter *filter;
  ssize_t method, type, i;
  double u, v, scale, margin=8.0;
  PixelInfo pixel;
  MagickBooleanType status;

  if (argc < 6)
    return(Fail(exception,"resample: IMAGE VIRTUAL-PIXEL FILTER SCALE"));
  image=Read(argv[2],exception);
  if (image == (Image *) NULL)
    return(Fail(exception,"read"));
  method=ParseCommandOption(MagickVirtualPixelOptions,MagickFalse,argv[3]);
  type=ParseCommandOption(MagickFilterOptions,MagickFalse,argv[4]);
  scale=atof(argv[5]);
  filter=AcquireResampleFilter(image,exception);
  if (method >= 0)
    (void) printf("virtual %d\n",(int) SetResampleFilterVirtualPixelMethod(filter,(VirtualPixelMethod) method));
  if (type >= 0)
    SetResampleFilter(filter,(FilterType) type);
  for (i=6; i < argc; i++)
    if (strncmp(argv[i],"margin=",7) == 0)
      margin=atof(argv[i]+7);
    else if (strncmp(argv[i],"interpolate=",12) == 0)
      (void) SetResampleFilterInterpolateMethod(filter,(PixelInterpolateMethod)
        ParseCommandOption(MagickInterpolateOptions,MagickFalse,argv[i]+12));
  if (scale > 0.0)
    ScaleResampleFilter(filter,scale,0.3*scale,-0.2*scale,scale);
  GetPixelInfo(image,&pixel);
  for (v=-margin; v <= (double) image->rows+margin; v+=0.5)
  {
    unsigned long h=2166136261UL;
    int hits=0;
    for (u=-margin; u <= (double) image->columns+margin; u+=0.5)
    {
      unsigned char bytes[64];
      int n;
      status=ResamplePixelColor(filter,u,v,&pixel,exception);
      n=FormatLocaleString((char *) bytes,sizeof(bytes),"%d %.4f %.4f %.4f %.4f;",(int) status,
        pixel.red,pixel.green,pixel.blue,pixel.alpha);
      h=(h ^ Fnv(bytes,(size_t) n))*16777619UL & 0xffffffffUL;
      hits+=(int) status;
    }
    (void) printf("v %.1f: %d %08lx\n",v,hits,h);
  }
  filter=DestroyResampleFilter(filter);
  Report(exception);
  image=DestroyImage(image);
  return(0);
}

/* token.c: GlobExpression over a pattern and expressions */
static int GlobCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* glob PATTERN CASE EXPRESSION...  (CASE: exact|nocase) prints 1/0 per expression;
     an expression "repeat:N:TEXT" is TEXT repeated N times */
  int i;
  MagickBooleanType nocase;
  if (argc < 5)
    return(Fail(exception,"glob: PATTERN exact|nocase EXPRESSION..."));
  nocase=strcmp(argv[3],"nocase") == 0 ? MagickTrue : MagickFalse;
  for (i=4; i < argc; i++)
  {
    char *expression=argv[i];
    char *built=(char *) NULL;
    if (strncmp(expression,"repeat:",7) == 0)
      {
        size_t n=(size_t) atol(expression+7), k;
        const char *text=strchr(expression+7,':');
        text=text != NULL ? text+1 : "";
        built=(char *) AcquireQuantumMemory(n*strlen(text)+1,1);
        *built='\0';
        for (k=0; k < n; k++) (void) strcat(built,text);
        expression=built;
      }
    (void) printf("%d %s\n",(int) GlobExpression(expression,argv[2],nocase),
      built != NULL ? argv[i] : expression);
    if (built != NULL) built=(char *) RelinquishMagickMemory(built);
  }
  return(0);
}

static int TokenizeCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* tokenize LINE MAXLEN WHITE BREAKS QUOTES ESCAPE FLAG: Tokenizer until the line ends
     (ESCAPE "-" for none; FLAG 0 as is, 1 upper case, 2 lower case) */
  TokenInfo *token_info;
  char token[256], breaker, quoted;
  int next=0, status, n=0;
  size_t length;
  if (argc != 9)
    return(Fail(exception,"tokenize: LINE MAXLEN WHITE BREAKS QUOTES ESCAPE FLAG"));
  length=(size_t) atol(argv[3]);
  if ((length == 0) || (length > sizeof(token)))
    length=sizeof(token);
  token_info=AcquireTokenInfo();
  (void) memset(token,0,sizeof(token));
  while ((status=Tokenizer(token_info,(unsigned) atoi(argv[8]),token,length,argv[2],argv[4],argv[5],argv[6],
           strcmp(argv[7],"-") == 0 ? '\0' : *argv[7],&breaker,&next,&quoted)) == 0)
  {
    (void) printf("[%s] breaker %d quoted %d next %d\n",token,(int) breaker,(int) quoted,next);
    if (++n > 200)
      break;
  }
  (void) printf("status %d next %d\n",status,next);
  token_info=DestroyTokenInfo(token_info);
  return(0);
}

/* color.c: colour tuples and names from a PixelInfo of doubles; IsEquivalent* */
extern MagickBooleanType IsEquivalentAlpha(const Image *,const PixelInfo *,const PixelInfo *);
extern MagickBooleanType IsEquivalentIntensity(const Image *,const PixelInfo *,const PixelInfo *);

static int ColorCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* color tuple R G B K A DEPTH COLORSPACE ALPHA     GetColorTuple, QueryColorname x4
     color equiv FUZZ R G B A R G B A                 IsEquivalentAlpha, IsEquivalentIntensity
     color subimage IMAGE TARGET FUZZ                 IsEquivalentImage */
  if ((argc == 11) && (strcmp(argv[2],"tuple") == 0))
    {
      PixelInfo pixel;
      char tuple[MagickPathExtent], name[MagickPathExtent];
      ssize_t cs;
      static const ComplianceType compliance[] = { SVGCompliance, X11Compliance, XPMCompliance,
        CSSCompliance, AllCompliance };
      size_t i;
      GetPixelInfo((Image *) NULL,&pixel);
      pixel.red=atof(argv[3]); pixel.green=atof(argv[4]); pixel.blue=atof(argv[5]);
      pixel.black=atof(argv[6]); pixel.alpha=atof(argv[7]);
      pixel.depth=(size_t) atol(argv[8]);
      cs=ParseCommandOption(MagickColorspaceOptions,MagickFalse,argv[9]);
      if (cs >= 0) pixel.colorspace=(ColorspaceType) cs;
      pixel.alpha_trait=atoi(argv[10]) != 0 ? BlendPixelTrait : UndefinedPixelTrait;
      *tuple='\0'; GetColorTuple(&pixel,MagickFalse,tuple); (void) printf("tuple %s\n",tuple);
      *tuple='\0'; GetColorTuple(&pixel,MagickTrue,tuple); (void) printf("hex %s\n",tuple);
      for (i=0; i < sizeof(compliance)/sizeof(*compliance); i++)
      {
        *name='\0';
        (void) printf("name %d %d %s\n",(int) compliance[i],(int) QueryColorname((Image *) NULL,&pixel,
          compliance[i],name,exception),name);
      }
      Report(exception);
      return(0);
    }
  if ((argc == 12) && (strcmp(argv[2],"equiv") == 0))
    {
      Image *image;
      PixelInfo p, q;
      ImageInfo *image_info=AcquireImageInfo();
      image=AcquireImage(image_info,exception);
      image->fuzz=atof(argv[3]);
      image->alpha_trait=BlendPixelTrait;  /* IsEquivalentAlpha compares only with alpha */
      GetPixelInfo(image,&p); GetPixelInfo(image,&q);
      p.red=atof(argv[4]); p.green=atof(argv[5]); p.blue=atof(argv[6]); p.alpha=atof(argv[7]);
      q.red=atof(argv[8]); q.green=atof(argv[9]); q.blue=atof(argv[10]); q.alpha=atof(argv[11]);
      p.alpha_trait=q.alpha_trait=BlendPixelTrait;
      (void) printf("alpha %d intensity %d\n",(int) IsEquivalentAlpha(image,&p,&q),
        (int) IsEquivalentIntensity(image,&p,&q));
      image=DestroyImage(image);
      image_info=DestroyImageInfo(image_info);
      return(0);
    }
  if ((argc == 6) && (strcmp(argv[2],"subimage") == 0))
    {
      Image *image=Read(argv[3],exception), *target=Read(argv[4],exception);
      ssize_t x=0, y=0;
      if ((image == (Image *) NULL) || (target == (Image *) NULL))
        return(Fail(exception,"read"));
      image->fuzz=atof(argv[5]);
      (void) printf("equivalent %d at %.20g,%.20g\n",(int) IsEquivalentImage(image,target,&x,&y,exception),
        (double) x,(double) y);
      Report(exception);
      target=DestroyImage(target);
      image=DestroyImage(image);
      return(0);
    }
  return(Fail(exception,"color: tuple R G B K A DEPTH COLORSPACE ALPHA | equiv FUZZ R G B A R G B A | subimage IMAGE TARGET FUZZ"));
}

/* stream.c: ReadStream with a handler that asks the streaming image for pixels (the stream
   cache methods), WriteStream with a handler that takes the encoded bytes */
static size_t stream_rows=0, stream_bytes=0;
static int stream_probe=1;
static unsigned long stream_hash=2166136261UL;

static size_t ReadRow(const Image *image,const void *pixels,const size_t columns)
{
  Quantum q[MaxPixelChannels];
  const Quantum *v;
  ExceptionInfo *sans=AcquireExceptionInfo();
  ssize_t x;
  size_t n=columns*GetPixelChannels(image)*sizeof(Quantum);
  stream_hash=(stream_hash ^ Fnv((const unsigned char *) pixels,n))*16777619UL & 0xffffffffUL;
  if ((stream_probe == 0) || (stream_rows >= 2))
    {
      stream_rows++;
      sans=DestroyExceptionInfo(sans);
      return(columns);
    }
  for (x=0; x < (ssize_t) columns; x+=(ssize_t) (columns/3+1))
  {
    (void) memset(q,0,sizeof(q));
    (void) printf("row %.20g x %.20g: virtual %d",(double) stream_rows,(double) x,
      (int) GetOneVirtualPixel(image,x,0,q,sans));
    (void) printf(" %.4f authentic %d",(double) q[0],(int) GetOneAuthenticPixel((Image *) image,x,0,q,sans));
    (void) printf(" %.4f\n",(double) q[0]);
  }
  {
    /* GetVirtualPixels reaches GetVirtualPixelStream: the row, a part of it, and outside it */
    static const ssize_t at[][4] = { { 0, 0, 0, 1 }, { 3, 0, 5, 1 }, { -2, 0, 4, 1 }, { 0, 1, 2, 1 } };
    size_t k;
    for (k=0; k < sizeof(at)/sizeof(*at); k++)
    {
      size_t w=at[k][2] == 0 ? columns : (size_t) at[k][2];
      const Quantum *p=GetVirtualPixels(image,at[k][0],at[k][1],w,(size_t) at[k][3],sans);
      (void) printf("  virtual pixels %.20g,%.20g %.20g: %s",(double) at[k][0],(double) at[k][1],
        (double) w,p != (const Quantum *) NULL ? "yes" : "no");
      if (p != (const Quantum *) NULL)
        (void) printf(" %08lx",Fnv((const unsigned char *) p,w*GetPixelChannels(image)*sizeof(Quantum)));
      (void) printf("\n");
    }
  }
  v=GetVirtualPixelQueue(image);
  (void) printf("  queue %s meta %s authentic-meta %s\n",v != NULL ? "yes" : "no",
    GetVirtualMetacontent(image) != NULL ? "yes" : "no",
    GetAuthenticMetacontent((Image *) image) != NULL ? "yes" : "no");
  sans=DestroyExceptionInfo(sans);
  stream_rows++;
  return(columns);
}

static size_t WriteBytes(const Image *magick_unused(image),const void *data,const size_t length)
{
  stream_hash=(stream_hash ^ Fnv((const unsigned char *) data,length))*16777619UL & 0xffffffffUL;
  stream_bytes+=length;
  return(length);
}

static int StreamCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* stream read IMAGE | stream write IMAGE FORMAT */
  ImageInfo *image_info=AcquireImageInfo();
  Image *image;
  if ((argc == 4) && ((strcmp(argv[2],"read") == 0) || (strcmp(argv[2],"plain") == 0)))
    {
      stream_probe=strcmp(argv[2],"read") == 0 ? 1 : 0;
      (void) CopyMagickString(image_info->filename,argv[3],MagickPathExtent);
      image=ReadStream(image_info,ReadRow,exception);
      (void) printf("rows %.20g hash %08lx\n",(double) stream_rows,stream_hash);
      Report(exception);
      if (image != (Image *) NULL) image=DestroyImageList(image);
    }
  else if ((argc == 5) && (strcmp(argv[2],"write") == 0))
    {
      image=Read(argv[3],exception);
      if (image == (Image *) NULL)
        return(Fail(exception,"read"));
      (void) FormatLocaleString(image_info->filename,MagickPathExtent,"%s:-",argv[4]);
      (void) CopyMagickString(image->filename,image_info->filename,MagickPathExtent);
      (void) printf("write %d",(int) WriteStream(image_info,image,WriteBytes,exception));
      (void) printf(" bytes %.20g hash %08lx\n",(double) stream_bytes,stream_hash);
      Report(exception);
      image=DestroyImageList(image);
    }
  else
    return(Fail(exception,"stream: read IMAGE | write IMAGE FORMAT"));
  image_info=DestroyImageInfo(image_info);
  return(0);
}

/* cache.c: the pixel cache in memory or on disk, with metacontent, its getters, a clone, a
   reshape and DestroyImagePixels */
extern MagickBooleanType SyncImagePixelCache(Image *,ExceptionInfo *);

static unsigned long HashRows(Image *image,ExceptionInfo *exception)
{
  unsigned long h=2166136261UL;
  ssize_t y;
  for (y=0; y < (ssize_t) image->rows; y++)
  {
    const Quantum *p=GetVirtualPixels(image,0,y,image->columns,1,exception);
    const void *meta;
    if (p == (const Quantum *) NULL)
      return(0);
    h=(h ^ Fnv((const unsigned char *) p,image->columns*GetPixelChannels(image)*sizeof(Quantum)))*16777619UL & 0xffffffffUL;
    meta=GetVirtualMetacontent(image);
    if ((meta != NULL) && (image->metacontent_extent != 0))
      h=(h ^ Fnv((const unsigned char *) meta,image->columns*image->metacontent_extent))*16777619UL & 0xffffffffUL;
  }
  return(h);
}

static int CacheCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* cache IMAGE memory|disk METACONTENT-EXTENT */
  Image *image, *clone;
  MagickSizeType length=0;
  ssize_t y, x, method;
  size_t meta;
  PixelInfo info;
  if (argc != 5)
    return(Fail(exception,"cache: IMAGE memory|disk METACONTENT-EXTENT"));
  if (strcmp(argv[3],"disk") == 0)
    {
      (void) SetMagickResourceLimit(MemoryResource,0);
      (void) SetMagickResourceLimit(MapResource,0);
    }
  image=Read(argv[2],exception);
  if (image == (Image *) NULL)
    return(Fail(exception,"read"));
  meta=(size_t) atol(argv[4]);
  if (meta != 0)
    {
      image->metacontent_extent=meta;
      (void) printf("sync %d\n",(int) SyncImagePixelCache(image,exception));
      for (y=0; y < (ssize_t) image->rows; y++)
      {
        Quantum *q=GetAuthenticPixels(image,0,y,image->columns,1,exception);
        unsigned char *m=(unsigned char *) GetAuthenticMetacontent(image);
        size_t k;
        if (q == (Quantum *) NULL)
          break;
        for (k=0; (m != NULL) && (k < image->columns*meta); k++)
          m[k]=(unsigned char) ((k*13+(size_t) y*7) & 0xff);
        (void) SyncAuthenticPixels(image,exception);
      }
    }
  (void) printf("rows %08lx\n",HashRows(image,exception));
  if ((meta != 0) && (image->columns > 4) && (image->rows > 3))
    {
      /* a region narrower than a row and several rows high: the cache copies it (Read/
         WritePixelCacheMetacontent) instead of handing out its own memory */
      size_t w=image->columns/2, h=image->rows/2, k;
      Quantum *q=GetAuthenticPixels(image,1,1,w,h,exception);
      unsigned char *m=(unsigned char *) GetAuthenticMetacontent(image);
      const void *vm;
      for (k=0; (q != NULL) && (m != NULL) && (k < w*h*meta); k++)
        m[k]=(unsigned char) ((k*29+5) & 0xff);
      if (q != NULL)
        (void) SyncAuthenticPixels(image,exception);
      if (GetVirtualPixels(image,2,1,w,h,exception) != (const Quantum *) NULL)
        {
          vm=GetVirtualMetacontent(image);
          (void) printf("region meta %08lx\n",vm != NULL ? Fnv((const unsigned char *) vm,w*h*meta) : 0UL);
        }
    }
  for (x=0; x < (ssize_t) image->columns; x+=(ssize_t) image->columns/3+1)
  {
    Quantum q[MaxPixelChannels];
    (void) memset(q,0,sizeof(q));
    (void) printf("authentic %.20g: %d %.4f\n",(double) x,(int) GetOneAuthenticPixel(image,x,
      (ssize_t) image->rows/2,q,exception),(double) q[0]);
  }
  (void) printf("cache pixels %s length %.20g\n",GetPixelCachePixels(image,&length,exception) != NULL ? "yes" : "no",
    (double) length);
  for (method=0; method <= (ssize_t) CheckerTileVirtualPixelMethod; method++)
  {
    if (method == (ssize_t) RandomVirtualPixelMethod)
      continue;
    for (x=-2; x <= (ssize_t) image->columns+1; x+=(ssize_t) image->columns/2+1)
    {
      (void) memset(&info,0,sizeof(info));
      (void) GetOneVirtualPixelInfo(image,(VirtualPixelMethod) method,x,-1,&info,exception);
      (void) printf("info %s %.20g: %.4f %.4f %.4f %.4f %s\n",CommandOptionToMnemonic(MagickVirtualPixelOptions,
        method),(double) x,info.red,info.green,info.blue,info.alpha,
        CommandOptionToMnemonic(MagickColorspaceOptions,(ssize_t) info.colorspace));
    }
  }
  clone=CloneImage(image,0,0,MagickTrue,exception);
  if (clone != (Image *) NULL)
    {
      Quantum *q;
      (void) printf("clone %08lx\n",HashRows(clone,exception));
      /* the clone shares the cache until it is written: then the cache is copied (on disk,
         ClonePixelCacheOnDisk) */
      q=GetAuthenticPixels(clone,0,0,1,1,exception);
      if (q != (Quantum *) NULL)
        {
          q[0]=(Quantum) (QuantumRange/3.0);
          (void) SyncAuthenticPixels(clone,exception);
        }
      (void) printf("clone written %08lx, original %08lx\n",HashRows(clone,exception),HashRows(image,exception));
      clone=DestroyImage(clone);
    }
  (void) printf("reshape %d",(int) ReshapePixelCache(image,image->rows,image->columns,exception));
  (void) printf(" %.20gx%.20g\n",(double) image->columns,(double) image->rows);
  DestroyImagePixels(image);  /* the cache's destroy handler: DestroyImagePixelCache */
  (void) printf("after destroy: cache %s\n",image->cache == NULL ? "gone" : "kept");
  Report(exception);
  /* not DestroyImage: it destroys the (now absent) pixels again and asserts; the process ends */
  return(0);
}

/* blob.c: blob input primitives over a file, SetBlobExtent over a file opened for writing */
static int BlobIOCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* blobio read FILE DISCARD | blobio extent OUT EXTENT */
  ImageInfo *image_info=AcquireImageInfo();
  Image *image=AcquireImage(image_info,exception);
  MagickBooleanType status;
  if ((argc == 5) && (strcmp(argv[2],"read") == 0))
    {
      char line[MagickPathExtent];
      int n=0;
      Image *other;
      (void) CopyMagickString(image->filename,argv[3],MagickPathExtent);
      status=OpenBlob(image_info,image,ReadBinaryBlobMode,exception);
      (void) printf("open %d size %.20g\n",(int) status,(double) GetBlobSize(image));
      if (status != MagickFalse)
        {
          (void) printf("discard %d tell %.20g\n",(int) DiscardBlobBytes(image,(MagickSizeType)
            atol(argv[4])),(double) TellBlob(image));
          (void) printf("msb long long %.20g error %d\n",(double) ReadBlobMSBLongLong(image),ErrorBlob(image));
          while (ReadBlobString(image,line) != (char *) NULL)
          {
            (void) printf("line %d: %.20g %08lx\n",n,(double) strlen(line),Fnv((const unsigned char *) line,
              strlen(line)));
            if (++n > 100)
              break;
          }
          (void) printf("eof %d error %d\n",EOFBlob(image),ErrorBlob(image));
          other=AcquireImage(image_info,exception);
          DuplicateBlob(other,image);
          (void) printf("duplicate size %.20g\n",(double) GetBlobSize(other));
          other=DestroyImage(other);
          (void) CloseBlob(image);
          status=OpenBlob(image_info,image,ReadBinaryBlobMode,exception);
          {
            char copy[MagickPathExtent];
            (void) CopyMagickString(copy,"copy.out",MagickPathExtent);
            (void) printf("image to file %d\n",(int) ImageToFile(image,copy,exception));
          }
          (void) CloseBlob(image);
        }
    }
  else if ((argc >= 5) && (strcmp(argv[2],"extent") == 0))
    {
      /* blobio extent OUT EXTENT [PREWRITE] [sync]: PREWRITE bytes written before the extent
         is set; sync sets MAGICK_SYNCHRONIZE (the posix_fallocate path) */
      FILE *file;
      long size=-1;
      if ((argc > 6) && (strcmp(argv[6],"sync") == 0))
        (void) setenv("MAGICK_SYNCHRONIZE","true",1);
      (void) CopyMagickString(image->filename,argv[3],MagickPathExtent);
      status=OpenBlob(image_info,image,WriteBinaryBlobMode,exception);
      if ((status != MagickFalse) && (argc > 5))
        {
          long k;
          for (k=0; k < atol(argv[5]); k++)
            (void) WriteBlobByte(image,(unsigned char) ('a'+k % 26));
          (void) printf("prewrite tell %.20g\n",(double) TellBlob(image));
        }
      if (status != MagickFalse)
        {
          (void) printf("extent %d\n",(int) SetBlobExtent(image,(MagickSizeType) atol(argv[4])));
          (void) WriteBlobString(image,"abc");
          (void) printf("tell %.20g\n",(double) TellBlob(image));
          (void) CloseBlob(image);
        }
      file=fopen(argv[3],"rb");
      if (file != (FILE *) NULL)
        {
          (void) fseek(file,0,SEEK_END);
          size=ftell(file);
          (void) fclose(file);
        }
      (void) printf("file size %ld\n",size);
    }
  else
    return(Fail(exception,"blobio: read FILE DISCARD | extent OUT EXTENT"));
  Report(exception);
  image=DestroyImage(image);
  image_info=DestroyImageInfo(image_info);
  return(0);
}

static size_t FromHex(const char *hex,unsigned char *out,size_t limit)
{
  size_t n=0,i,len=strlen(hex);
  for (i=0; (i+1 < len) && (n < limit); i+=2)
    {
      int hi=hex[i],lo=hex[i+1];
      hi=(hi<='9')?hi-'0':((hi|0x20)-'a'+10);
      lo=(lo<='9')?lo-'0':((lo|0x20)-'a'+10);
      out[n++]=(unsigned char) ((hi<<4)|lo);
    }
  return(n);
}

static void PrintHex(const unsigned char *b,size_t n)
{
  size_t i;
  for (i=0; i < n; i++) (void) printf("%02x",b[i]);
  (void) printf("\n");
}

static StringInfo *AllBytes(size_t length,unsigned char value)
{
  StringInfo *s=AcquireStringInfo(length);
  if (length != 0) (void) memset(GetStringInfoDatum(s),value,length);
  return(s);
}

static int StringCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* string escape SRC ESC                 EscapeString
     string sanitize HEX                   SanitizeString (hex in/out: control bytes are reachable)
     string compare LENA LENB              CompareStringInfo (equal all-'a' prefix: the length branch)
     string concat DEST SRC LEN            ConcatenateMagickString (small LEN forces truncation)
     string configfile FILE                ConfigureFileToStringInfo */
  if ((argc == 5) && (strcmp(argv[2],"escape") == 0))
    {
      char *r=EscapeString(argv[3],argv[4][0]);
      (void) printf("escape %s\n",r);
      r=DestroyString(r);
      return(0);
    }
  if ((argc == 4) && (strcmp(argv[2],"sanitize") == 0))
    {
      unsigned char in[MagickPathExtent]; char *src,*r;
      size_t n=FromHex(argv[3],in,sizeof(in)-1);
      in[n]='\0';
      src=(char *) in;
      r=SanitizeString(src);
      (void) printf("sanitize "); PrintHex((unsigned char *) r,strlen(r));
      r=DestroyString(r);
      return(0);
    }
  if ((argc == 5) && (strcmp(argv[2],"compare") == 0))
    {
      StringInfo *a=AllBytes((size_t) atol(argv[3]),'a'),*b=AllBytes((size_t) atol(argv[4]),'a');
      (void) printf("compare %d\n",CompareStringInfo(a,b));
      a=DestroyStringInfo(a); b=DestroyStringInfo(b);
      return(0);
    }
  if ((argc == 6) && (strcmp(argv[2],"concat") == 0))
    {
      size_t length=(size_t) atol(argv[5]),count;
      char *buffer=(char *) AcquireQuantumMemory(length+1,sizeof(*buffer));
      if (buffer == (char *) NULL) return(1);
      *buffer='\0';
      (void) CopyMagickString(buffer,argv[3],length);
      count=ConcatenateMagickString(buffer,argv[4],length);
      (void) printf("concat %s count %.20g\n",buffer,(double) count);
      buffer=(char *) RelinquishMagickMemory(buffer);
      return(0);
    }
  if ((argc == 4) && (strcmp(argv[2],"configfile") == 0))
    {
      StringInfo *s=ConfigureFileToStringInfo(argv[3]);
      if (s == (StringInfo *) NULL) { (void) printf("configfile (none)\n"); return(0); }
      { size_t i,len=GetStringInfoLength(s),sum=0;
        const unsigned char *d=GetStringInfoDatum(s);
        for (i=0; i < len; i++) sum=(sum+d[i]) & 0xffffff;
        (void) printf("configfile length %.20g sum %.20g\n",(double) len,(double) sum); }
      s=DestroyStringInfo(s);
      return(0);
    }
  (void) fprintf(stderr,"string escape|sanitize|compare|concat|configfile ...\n");
  return(2);
}

static void PrintMetrics(const char *what,MagickBooleanType status,const TypeMetric *m)
{
  (void) printf("%s %d ppem %.6g,%.6g ascent %.6g descent %.6g width %.6g height %.6g "
    "max_advance %.6g underline %.6g,%.6g bounds %.6g,%.6g %.6g,%.6g origin %.6g,%.6g\n",what,
    (int) status,m->pixels_per_em.x,m->pixels_per_em.y,m->ascent,m->descent,m->width,m->height,
    m->max_advance,m->underline_position,m->underline_thickness,m->bounds.x1,m->bounds.y1,
    m->bounds.x2,m->bounds.y2,m->origin.x,m->origin.y);
}

static int MetricsCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* metrics FONT POINTSIZE TEXT [KEY=VALUE...]   GetTypeMetrics and GetMultilineTypeMetrics:
     the TypeMetric fields that label:, caption: and -annotate never print (RenderFreetype's height,
     max_advance, bounds, underline). KEY: stroke=WIDTH antialias=0 kerning=K density=D
     direction=rtl gravity=NAME */
  ImageInfo *image_info;
  Image *image;
  DrawInfo *draw_info;
  TypeMetric metrics;
  MagickBooleanType status;
  int i;
  if (argc < 5)
    return(Fail(exception,"metrics FONT POINTSIZE TEXT [KEY=VALUE...]"));
  image_info=AcquireImageInfo();
  image=AcquireImage(image_info,exception);
  draw_info=AcquireDrawInfo();
  (void) CloneString(&draw_info->font,argv[2]);
  draw_info->pointsize=atof(argv[3]);
  (void) CloneString(&draw_info->text,argv[4]);
  for (i=5; i < argc; i++)
  {
    const char *v=strchr(argv[i],'=');
    if (v == (const char *) NULL) continue;
    v++;
    if (strncmp(argv[i],"stroke=",7) == 0)
      {
        draw_info->stroke_width=atof(v);
        (void) QueryColorCompliance("black",AllCompliance,&draw_info->stroke,exception);
      }
    else if (strncmp(argv[i],"antialias=",10) == 0)
      draw_info->text_antialias=atoi(v) != 0 ? MagickTrue : MagickFalse;
    else if (strncmp(argv[i],"kerning=",8) == 0)
      draw_info->kerning=atof(v);
    else if (strncmp(argv[i],"density=",8) == 0)
      (void) CloneString(&draw_info->density,v);
    else if (strncmp(argv[i],"direction=",10) == 0)
      draw_info->direction=strcmp(v,"rtl") == 0 ? RightToLeftDirection : LeftToRightDirection;
    else if (strncmp(argv[i],"encoding=",9) == 0)
      (void) CloneString(&draw_info->encoding,v);
    else if (strncmp(argv[i],"texthex=",8) == 0)
      {
        /* raw bytes (Latin-1 text is not valid UTF-8, and an argument cannot carry it intact) */
        unsigned char bytes[MagickPathExtent];
        size_t n=FromHex(v,bytes,sizeof(bytes)-1);
        bytes[n]='\0';
        (void) CloneString(&draw_info->text,(const char *) bytes);
      }
  }
  (void) memset(&metrics,0,sizeof(metrics));
  status=GetTypeMetrics(image,draw_info,&metrics,exception);
  PrintMetrics("single",status,&metrics);
  (void) memset(&metrics,0,sizeof(metrics));
  status=GetMultilineTypeMetrics(image,draw_info,&metrics,exception);
  PrintMetrics("multi",status,&metrics);
  Report(exception);
  draw_info=DestroyDrawInfo(draw_info);
  image=DestroyImage(image);
  image_info=DestroyImageInfo(image_info);
  return(0);
}

static int PathAuthCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* pathauth PATH...   builds real/f.txt, real/sub/g.txt and the symbolic links link -> real,
     real/slink -> sub and flink -> real/f.txt in the case directory (a case's files cannot be
     links), then prints IsPathAuthorized(read) for each PATH. A PATH starting with '+' is made
     absolute (the current directory prepended), one starting with 'L<n>:' gets an n-character
     component of 'a' inserted after real/ (path length around MagickPathExtent). */
  char cwd[MagickPathExtent];
  int i;
  FILE *f;
  (void) exception;
  (void) mkdir("real",0755); (void) mkdir("real/sub",0755);
  if ((f=fopen("real/f.txt","w")) != (FILE *) NULL) { (void) fputs("f\n",f); (void) fclose(f); }
  if ((f=fopen("real/sub/g.txt","w")) != (FILE *) NULL) { (void) fputs("g\n",f); (void) fclose(f); }
  (void) symlink("real","link"); (void) symlink("sub","real/slink"); (void) symlink("real/f.txt","flink");
  if (getcwd(cwd,sizeof(cwd)) == (char *) NULL) *cwd='\0';
  for (i=2; i < argc; i++)
  {
    char *path=(char *) AcquireQuantumMemory(3*MagickPathExtent,1);
    const char *shown=argv[i];
    if (path == (char *) NULL) return(1);
    if (*argv[i] == '+')
      (void) FormatLocaleString(path,3*MagickPathExtent,"%s/%s",cwd,argv[i]+1);
    else if (strncmp(argv[i],"L",1) == 0 && strchr(argv[i],':') != (char *) NULL)
      {
        size_t n=(size_t) atol(argv[i]+1),k;
        const char *rest=strchr(argv[i],':')+1;
        (void) CopyMagickString(path,"real/",3*MagickPathExtent);
        for (k=0; k < n && k+6 < 3*MagickPathExtent; k++) path[5+k]='a';
        path[5+k]='\0';
        (void) ConcatenateMagickString(path,rest,3*MagickPathExtent);
      }
    else
      (void) CopyMagickString(path,argv[i],3*MagickPathExtent);
    (void) printf("%s %d\n",shown,(int) IsPathAuthorized(ReadPolicyRights,path));
    path=(char *) RelinquishMagickMemory(path);
  }
  return(0);
}

static int NextImageCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* nextimage FILE   image.c: AcquireNextImage (the next frame's name comes from image_info when
     given, from the image otherwise; it shares the image's blob) and DisassociateImageStream (the
     next frame gets a blob of its own). Reads FILE as the shared blob. */
  ImageInfo *image_info, *next_info;
  Image *image, *next;
  int c;
  if (argc != 3) return(Fail(exception,"nextimage FILE"));
  image_info=AcquireImageInfo();
  (void) CopyMagickString(image_info->filename,argv[2],MagickPathExtent);
  image=AcquireImage(image_info,exception);
  (void) CopyMagickString(image->filename,argv[2],MagickPathExtent);
  if (OpenBlob(image_info,image,ReadBinaryBlobMode,exception) == MagickFalse)
    return(Fail(exception,"nextimage: open"));
  c=ReadBlobByte(image); c=ReadBlobByte(image); c=ReadBlobByte(image);
  (void) printf("image tell %.20g size %.20g last %d\n",(double) TellBlob(image),(double) GetBlobSize(image),c);
  next_info=CloneImageInfo(image_info);
  (void) CopyMagickString(next_info->filename,"from-image-info",MagickPathExtent);
  AcquireNextImage(next_info,image,exception);
  next=GetNextImageInList(image);
  if (next == (Image *) NULL) return(Fail(exception,"nextimage: no next"));
  (void) printf("next filename %s scene %.20g endian %d tell %.20g size %.20g\n",next->filename,(double) next->scene,
    (int) next->endian,(double) TellBlob(next),(double) GetBlobSize(next));
  DisassociateImageStream(next);
  /* the next frame now has a blob of its own: closing it must leave the image's stream open */
  (void) CloseBlob(next);
  c=ReadBlobByte(image);
  (void) printf("after closing next: image reads %d tell %.20g\n",c,(double) TellBlob(image));
  /* without an image_info the next frame keeps the image's name */
  AcquireNextImage((ImageInfo *) NULL,next,exception);
  if (GetNextImageInList(next) != (Image *) NULL)
    (void) printf("third filename %s scene %.20g\n",GetNextImageInList(next)->filename,
      (double) GetNextImageInList(next)->scene);
  (void) CloseBlob(image);
  Report(exception);
  return(0);
}

static void PrintDrawInfo(const char *what,const DrawInfo *d)
{
  size_t i;
  (void) printf("%s encoding %s family %s fill %g,%g,%g,%g stroke %g,%g,%g,%g undercolor %g,%g,%g,%g "
    "gravity %d interline %g interword %g kerning %g stroke_width %g style %d weight %.20g word_break %d "
    "direction %d\n",what,d->encoding ? d->encoding : "-",d->family ? d->family : "-",
    d->fill.red,d->fill.green,d->fill.blue,d->fill.alpha,d->stroke.red,d->stroke.green,d->stroke.blue,
    d->stroke.alpha,d->undercolor.red,d->undercolor.green,d->undercolor.blue,d->undercolor.alpha,
    (int) d->gravity,d->interline_spacing,d->interword_spacing,d->kerning,d->stroke_width,(int) d->style,
    (double) d->weight,(int) d->word_break,(int) d->direction);
  (void) printf("%s id %s primitive %s metrics %s clip_mask %s stops %.20g",what,d->id ? d->id : "-",
    d->primitive ? d->primitive : "-",d->metrics ? d->metrics : "-",d->clip_mask ? d->clip_mask : "-",
    (double) d->gradient.number_stops);
  for (i=0; (d->gradient.stops != (StopInfo *) NULL) && (i < d->gradient.number_stops); i++)
    (void) printf(" %g:%g,%g,%g",d->gradient.stops[i].offset,d->gradient.stops[i].color.red,
      d->gradient.stops[i].color.green,d->gradient.stops[i].color.blue);
  (void) printf("\n");
}

static int DrawInfoCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* drawinfo [KEY=VALUE...]   draw.c: GetDrawInfo from image options (encoding, family, fill,
     gravity, interline-spacing, interword-spacing, kerning, stroke, strokewidth, style, undercolor,
     weight, word-break, direction), then CloneDrawInfo of a draw info with an id, a primitive, a
     metrics file, a clip mask and two gradient stops; both printed. */
  ImageInfo *image_info=AcquireImageInfo();
  DrawInfo *draw_info, *clone;
  int i;
  for (i=2; i < argc; i++)
  {
    char key[MagickPathExtent];
    const char *v=strchr(argv[i],'=');
    if (v == (const char *) NULL) continue;
    (void) CopyMagickString(key,argv[i],(size_t) (v-argv[i])+1);
    (void) SetImageOption(image_info,key,v+1);
  }
  draw_info=CloneDrawInfo(image_info,(DrawInfo *) NULL);
  PrintDrawInfo("get",draw_info);
  (void) CloneString(&draw_info->id,"shape-1");
  (void) CloneString(&draw_info->primitive,"circle 5,5 5,8");
  (void) CloneString(&draw_info->metrics,"metrics.afm");
  (void) CloneString(&draw_info->clip_mask,"clip-1");
  draw_info->gradient.number_stops=2;
  draw_info->gradient.stops=(StopInfo *) AcquireQuantumMemory(2,sizeof(*draw_info->gradient.stops));
  (void) memset(draw_info->gradient.stops,0,2*sizeof(*draw_info->gradient.stops));
  draw_info->gradient.stops[0].offset=0.25; draw_info->gradient.stops[0].color.red=QuantumRange;
  draw_info->gradient.stops[1].offset=0.75; draw_info->gradient.stops[1].color.blue=QuantumRange;
  clone=CloneDrawInfo(image_info,draw_info);
  PrintDrawInfo("clone",clone);
  clone=DestroyDrawInfo(clone);
  draw_info=DestroyDrawInfo(draw_info);
  image_info=DestroyImageInfo(image_info);
  Report(exception);
  return(0);
}

static int MemoryCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* memory   allocations exactly at, and one byte over, the policy's max-memory-request (16 MiB at
     least): the boundary a command-line case would need a 16 MiB input to touch. */
  size_t max=GetMaxMemoryRequest(),sizes[2];
  int i;
  (void) argc; (void) argv; (void) exception;
  (void) printf("max %.20g\n",(double) max);
  if (max > ((size_t) 64*1024*1024))
    {
      (void) printf("no limit set\n");
      return(0);
    }
  sizes[0]=max; sizes[1]=max+1;
  for (i=0; i < 2; i++)
  {
    void *p=AcquireQuantumMemory(sizes[i],1),*q,*r;
    (void) printf("acquire %s %s\n",i == 0 ? "at" : "over",p != NULL ? "ok" : "refused");
    if (p != NULL) p=RelinquishMagickMemory(p);
    q=AcquireQuantumMemory(16,1);
    q=ResizeQuantumMemory(q,sizes[i],1);
    (void) printf("resize %s %s\n",i == 0 ? "at" : "over",q != NULL ? "ok" : "refused");
    if (q != NULL) q=RelinquishMagickMemory(q);
    r=AcquireAlignedMemory(sizes[i],1);
    (void) printf("aligned %s %s\n",i == 0 ? "at" : "over",r != NULL ? "ok" : "refused");
    if (r != NULL) r=RelinquishAlignedMemory(r);
  }
  return(0);
}

static int SymlinkCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* symlink SOURCEFILE   AcquireUniqueSymbolicLink to a fresh destination (a symlink, or a copy
     when policy forbids symlinks or shred is set), then read the destination back. The name is
     random, so only the status and the destination's content (= the source's) are printed. */
  char destination[MagickPathExtent];
  MagickBooleanType status;
  (void) exception;
  if (argc != 3) { (void) fprintf(stderr,"symlink SOURCEFILE\n"); return(2); }
  *destination='\0';
  status=AcquireUniqueSymbolicLink(argv[2],destination);
  (void) printf("status %d\n",(int) status);
  if (status != MagickFalse)
    {
      struct stat link_attributes;
      FILE *f;
      /* a symbolic link where policy allows one, a copy otherwise: the function's own contract */
      (void) printf("link %d\n",(lstat(destination,&link_attributes) == 0) &&
        S_ISLNK(link_attributes.st_mode) ? 1 : 0);
      f=fopen(destination,"rb");
      if (f != (FILE *) NULL)
        {
          int c; size_t sum=0,n=0;
          while ((c=fgetc(f)) != EOF) { sum=(sum+(size_t) c) & 0xffffff; n++; }
          (void) fclose(f);
          (void) printf("content length %.20g sum %.20g\n",(double) n,(double) sum);
        }
      else
        (void) printf("content (unreadable)\n");
      (void) RelinquishUniqueFileResource(destination);
    }
  return(0);
}

static int ConfigureCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* configure   lists the configure entries after the case directory was put first on
     MAGICK_CONFIGURE_PATH (main does it before MagickCoreGenesis), so LoadConfigureCache parses the
     case's own configure.xml, which the command line never does (the build's is found first). Prints
     name, value and stealth, not the path (it names the machine's case directory). */
  const ConfigureInfo **list;
  size_t n=0,k;
  (void) argc; (void) argv;
  list=GetConfigureInfoList("*",&n,exception);
  for (k=0; k < n; k++)
    if (strcmp(list[k]->path,"[built-in]") != 0)
      (void) printf("%s = %s%s\n",list[k]->name,list[k]->value,list[k]->stealth != MagickFalse ? " (stealth)" : "");
  (void) printf("entries %.20g\n",(double) n);
  if (list != (const ConfigureInfo **) NULL)
    list=(const ConfigureInfo **) RelinquishMagickMemory((void *) list);
  Report(exception);
  return(0);
}

static int LogCfgCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* logcfg [EVENTS]   with the case directory first on MAGICK_CONFIGURE_PATH (see main), so the
     case's own log.xml is parsed first and governs logging: ListLogInfo's section for it (its path
     printed as CASE), IsEventLogging, then, if EVENTS is given, SetLogEventMask(EVENTS) and one
     LogMagickEvent each of Annotate and Trace through the case's handlers. */
  char cwd[MagickPathExtent], line[3*MagickPathExtent];
  FILE *f;
  int show=0;
  if (getcwd(cwd,sizeof(cwd)) == (char *) NULL) *cwd='\0';
  f=tmpfile();
  if (f == (FILE *) NULL) return(1);
  (void) ListLogInfo(f,exception);
  rewind(f);
  while (fgets(line,sizeof(line),f) != (char *) NULL)
  {
    if (strncmp(line,"Path: ",6) == 0)
      {
        show=strstr(line,cwd) != (char *) NULL ? 1 : 0;
        if (show != 0) (void) printf("Path: CASE\n");
        continue;
      }
    if (show != 0) (void) fputs(line,stdout);
  }
  (void) fclose(f);
  (void) printf("event logging %d\n",(int) IsEventLogging());
  if (argc > 2)
    {
      (void) SetLogEventMask(argv[2]);
      (void) printf("after mask %s: event logging %d\n",argv[2],(int) IsEventLogging());
      (void) fflush(stdout);
      (void) LogMagickEvent(AnnotateEvent,GetMagickModule(),"an annotate event");
      (void) LogMagickEvent(TraceEvent,GetMagickModule(),"a trace event");
      (void) fflush(stdout);
    }
  Report(exception);
  return(0);
}

static int MimeCfgCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* mimecfg [name=FILENAME] HEX|-|empty...   with the case directory first on MAGICK_CONFIGURE_PATH
     (see main), so the case's own mime.xml is parsed first: GetMimeInfo on each byte string (hex;
     - is a NULL magic, empty a zero length), with the filename set by the last name= (none: NULL).
     Prints the type and description found (MimeInfo is opaque, so its path cannot be shown). */
  const char *filename=(const char *) NULL;
  unsigned char bytes[256];
  int k;
  for (k=2; k < argc; k++)
  {
    const MimeInfo *info;
    const unsigned char *magic=bytes;
    size_t length=0;
    if (strncmp(argv[k],"name=",5) == 0)
      {
        filename=*(argv[k]+5) != '\0' ? argv[k]+5 : (const char *) NULL;
        continue;
      }
    if (strcmp(argv[k],"-") == 0)
      magic=(const unsigned char *) NULL;
    else if (strcmp(argv[k],"empty") != 0)
      length=FromHex(argv[k],bytes,sizeof(bytes));
    info=GetMimeInfo(filename,magic,length,exception);
    if (info == (const MimeInfo *) NULL)
      (void) printf("%s %s: none\n",filename != (const char *) NULL ? filename : "-",argv[k]);
    else
      (void) printf("%s %s: %s (%s)\n",filename != (const char *) NULL ? filename : "-",argv[k],
        GetMimeType(info),GetMimeDescription(info));
  }
  Report(exception);
  return(0);
}

static void ReplaceAll(char *text,size_t size,const char *from,const char *to)
{
  /* replaces every occurrence of from in text (NUL-terminated, size bytes) by to */
  char *p, *copy;
  size_t n=strlen(from);
  if ((n == 0) || (strstr(text,from) == (char *) NULL)) return;
  copy=AcquireString(text);
  *text='\0';
  for (p=copy; *p != '\0'; )
  {
    if (strncmp(p,from,n) == 0) { (void) ConcatenateMagickString(text,to,size); p+=n; continue; }
    { char c[2]; c[0]=(*p++); c[1]='\0'; (void) ConcatenateMagickString(text,c,size); }
  }
  copy=DestroyString(copy);
}

static void DelegateReport(ExceptionInfo *exception,const char *self,const char *cwd)
{
  /* the exception's severity, reason and description, with the driver's own path shown as
     IMDRIVER and the case directory as CASE (both name the machine), then cleared */
  char text[3*MagickPathExtent];
  if (exception->severity == UndefinedException) return;
  (void) snprintf(text,sizeof(text),"exception %d %s (%s)",(int) exception->severity,
    exception->reason != NULL ? exception->reason : "",exception->description != NULL ?
    exception->description : "");
  ReplaceAll(text,sizeof(text),self,"IMDRIVER");
  if (*cwd != '\0') ReplaceAll(text,sizeof(text),cwd,"CASE");
  (void) printf("%s\n",text);
  ClearMagickException(exception);
}

static int CompareNames(const void *x,const void *y)
{
  return(strcmp(*(char * const *) x,*(char * const *) y));
}

static void PrintDelegate(const DelegateInfo *info)
{
  (void) printf("  decode %s encode %s mode %.20g thread %d spawn %d stealth %d commands \"%s\"\n",
    info->decode != NULL ? info->decode : "(null)",info->encode != NULL ? info->encode : "(null)",
    (double) GetDelegateMode(info),(int) GetDelegateThreadSupport(info),(int) info->spawn,
    (int) info->stealth,GetDelegateCommands(info) != NULL ? GetDelegateCommands(info) : "(null)");
}

static int DelegateCfgCmd(int argc,char **argv,ExceptionInfo *exception)
{
  /* delegatecfg OP...   with the case directory first on MAGICK_CONFIGURE_PATH (see main), so the
     case's own delegates.xml is parsed first. OPs, in order:
       info=DECODE,ENCODE   GetDelegateInfo (an empty name is NULL), printed field by field
       cmd=DECODE,ENCODE    GetDelegateCommand on the current image (rose:, filename a/b/rose.miff)
       list=PATTERN         GetDelegateInfoList, the case's own entries only
       listinfo             ListDelegateInfo, the case's section only (its path printed as CASE)
       ext=COMMAND          ExternalDelegateCommand(synchronous,quiet,COMMAND,no message), with
       extv=COMMAND         @SELF replaced by this driver's path (extv: verbose)
       invoke=DECODE,ENCODE InvokeDelegate on in.dat to out.dat (see below)
       quality= units= xres= yres= rows= columns= extent= scenes= alpha= file=   set the image's
                            (or, for scenes, the image_info's) field, for cmd's property letters
     After each op any exception is printed and cleared. */
  char cwd[MagickPathExtent], self[MagickPathExtent];
  Image *image;
  ImageInfo *image_info;
  int k;
  if (getcwd(cwd,sizeof(cwd)) == (char *) NULL) *cwd='\0';
  if (realpath(argv[0],self) == (char *) NULL) (void) CopyMagickString(self,argv[0],sizeof(self));
  image_info=AcquireImageInfo();
  (void) CopyMagickString(image_info->filename,"rose:",MagickPathExtent);
  image=ReadImage(image_info,exception);
  if (image == (Image *) NULL) return(Fail(exception,"delegatecfg: rose:"));
  (void) CopyMagickString(image->magick_filename,"a/b/rose.miff",MagickPathExtent);
  (void) CopyMagickString(image_info->filename,"out.png",MagickPathExtent);
  for (k=2; k < argc; k++)
  {
    char name[MagickPathExtent], *value, *comma;
    (void) CopyMagickString(name,argv[k],sizeof(name));
    value=strchr(name,'=');
    if (value != (char *) NULL) *value++='\0'; else value=name+strlen(name);
    (void) printf("%s\n",argv[k]);
    if ((strcmp(name,"info") == 0) || (strcmp(name,"cmd") == 0))
      {
        const char *decode=value, *encode="";
        comma=strchr(value,',');
        if (comma != (char *) NULL) { *comma='\0'; encode=comma+1; }
        if (*decode == '\0') decode=(const char *) NULL;
        if (*encode == '\0') encode=(const char *) NULL;
        if (*name == 'i')
          {
            const DelegateInfo *info=GetDelegateInfo(decode,encode,exception);
            if (info == (const DelegateInfo *) NULL) (void) printf("  none\n");
            else PrintDelegate(info);
          }
        else
          {
            char *command=GetDelegateCommand(image_info,image,decode,encode,exception);
            (void) printf("  command %s\n",command != (char *) NULL ? command : "(null)");
            if (command != (char *) NULL) command=DestroyString(command);
          }
      }
    else if (strcmp(name,"invoke") == 0)
      {
        /* InvokeDelegate on the image named in.dat (an existing file, written here) and the output
           out.dat; prints the status, whether each file still exists, and whether the image's
           filename and magick came back changed (not the names: they are unique temporary ones) */
        const char *decode=value, *encode="";
        FILE *f=fopen("in.dat","wb");
        MagickBooleanType status;
        if (f != (FILE *) NULL) { (void) fputs("input",f); (void) fclose(f); }
        comma=strchr(value,',');
        if (comma != (char *) NULL) { *comma='\0'; encode=comma+1; }
        if (*decode == '\0') decode=(const char *) NULL;
        if (*encode == '\0') encode=(const char *) NULL;
        (void) CopyMagickString(image->filename,"in.dat",MagickPathExtent);
        (void) CopyMagickString(image->magick,"ROSE",MagickPathExtent);
        (void) CopyMagickString(image_info->filename,"out.dat",MagickPathExtent);
        status=InvokeDelegate(image_info,image,decode,encode,exception);
        (void) printf("  status %d in.dat %d out.dat %d filename %s magick %s\n",(int) status,
          access("in.dat",F_OK) == 0 ? 1 : 0,access("out.dat",F_OK) == 0 ? 1 : 0,
          strcmp(image->filename,"in.dat") == 0 ? "in.dat" : "changed",image->magick);
        (void) remove("out.dat");
        {
          /* and the files left in the case directory, by name (the case directory is the
             temporary path too) */
          char **names;
          size_t n=0, j;
          names=ListFiles(".","*",&n);
          if (names != (char **) NULL)
            {
              qsort(names,n,sizeof(*names),CompareNames);
              (void) printf("  files");
              for (j=0; j < n; j++)
              {
                /* a temporary file left behind has a unique name: shown as magick-TMP, removed */
                if (strncmp(names[j],"magick-",7) == 0)
                  { (void) printf(" magick-TMP"); (void) remove(names[j]); }
                else
                  (void) printf(" %s",names[j]);
                names[j]=DestroyString(names[j]);
              }
              (void) printf("\n");
              names=(char **) RelinquishMagickMemory(names);
            }
        }
      }
    else if (strcmp(name,"list") == 0)
      {
        size_t n=0, j;
        const DelegateInfo **list=GetDelegateInfoList(value,&n,exception);
        for (j=0; j < n; j++)
          if (strstr(list[j]->path,cwd) != (char *) NULL) PrintDelegate(list[j]);
        if (list != (const DelegateInfo **) NULL)
          list=(const DelegateInfo **) RelinquishMagickMemory((void *) list);
      }
    else if (strcmp(name,"listinfo") == 0)
      {
        char line[3*MagickPathExtent];
        int show=0;
        FILE *f=tmpfile();
        if (f == (FILE *) NULL) return(1);
        (void) ListDelegateInfo(f,exception);
        rewind(f);
        while (fgets(line,sizeof(line),f) != (char *) NULL)
        {
          if (strncmp(line,"Path: ",6) == 0)
            {
              show=strstr(line,cwd) != (char *) NULL ? 1 : 0;
              if (show != 0) (void) printf("Path: CASE\n");
              continue;
            }
          if (show != 0) (void) fputs(line,stdout);
        }
        (void) fclose(f);
      }
    else if ((strcmp(name,"ext") == 0) || (strcmp(name,"extv") == 0))
      {
        char command[3*MagickPathExtent];
        int status;
        (void) CopyMagickString(command,value,sizeof(command));
        ReplaceAll(command,sizeof(command),"@SELF",self);
        (void) fflush(stdout);
        status=ExternalDelegateCommand(MagickFalse,name[3] == 'v' ? MagickTrue : MagickFalse,command,
          (char *) NULL,exception);
        (void) printf("  status %d\n",status);
      }
    else if (strcmp(name,"quality") == 0) image->quality=(size_t) atol(value);
    else if (strcmp(name,"units") == 0) image->units=(ResolutionType) atoi(value);
    else if (strcmp(name,"xres") == 0) image->resolution.x=strcmp(value,"eps") == 0 ? MagickEpsilon : atof(value);
    else if (strcmp(name,"yres") == 0) image->resolution.y=strcmp(value,"eps") == 0 ? MagickEpsilon : atof(value);
    else if (strcmp(name,"rows") == 0) image->rows=(size_t) atol(value);
    else if (strcmp(name,"columns") == 0) image->columns=(size_t) atol(value);
    else if (strcmp(name,"extent") == 0) image->extent=(MagickSizeType) atol(value);
    else if (strcmp(name,"scenes") == 0) image_info->number_scenes=(size_t) atol(value);
    else if (strcmp(name,"alpha") == 0) image->alpha_trait=atoi(value) != 0 ? BlendPixelTrait : UndefinedPixelTrait;
    else if (strcmp(name,"file") == 0) (void) CopyMagickString(image->magick_filename,value,MagickPathExtent);
    else (void) printf("  unknown op\n");
    (void) fflush(stdout);
    DelegateReport(exception,self,cwd);
  }
  image=DestroyImage(image);
  image_info=DestroyImageInfo(image_info);
  return(0);
}

int main(int argc,char **argv)
{
  ExceptionInfo *exception;
  int status;

  if (argc < 2)
    {
      (void) fprintf(stderr,"imdriver gradient|mask|getmask|acquire|list|mime ...\n");
      return(2);
    }
  if ((strcmp(argv[1],"configure") == 0) || (strcmp(argv[1],"logcfg") == 0) ||
      (strcmp(argv[1],"mimecfg") == 0) || (strcmp(argv[1],"delegatecfg") == 0))
    {
      char cwd[MagickPathExtent], value[3*MagickPathExtent];
      const char *old=getenv("MAGICK_CONFIGURE_PATH");
      if (getcwd(cwd,sizeof(cwd)) != (char *) NULL)
        {
          (void) snprintf(value,sizeof(value),"%s%s%s",cwd,old != (const char *) NULL ? ":" : "",
            old != (const char *) NULL ? old : "");
          (void) setenv("MAGICK_CONFIGURE_PATH",value,1);
        }
    }
  MagickCoreGenesis(*argv,MagickFalse);
  exception=AcquireExceptionInfo();
  if (strcmp(argv[1],"gradient") == 0) status=Gradient(argc,argv,exception);
  else if (strcmp(argv[1],"mask") == 0) status=Mask(argc,argv,exception);
  else if (strcmp(argv[1],"getmask") == 0) status=GetMask(argc,argv,exception);
  else if (strcmp(argv[1],"acquire") == 0) status=Acquire(argc,argv,exception);
  else if (strcmp(argv[1],"list") == 0) status=List(argc,argv,exception);
  else if (strcmp(argv[1],"mime") == 0) status=Mime(argc,argv,exception);
  else if (strcmp(argv[1],"pixels") == 0) status=Pixels(argc,argv,exception);
  else if (strcmp(argv[1],"linkedlist") == 0) status=List2(argc,argv,exception);
  else if (strcmp(argv[1],"splaytree") == 0) status=Tree(argc,argv,exception);
  else if (strcmp(argv[1],"cacheview") == 0) status=View(argc,argv,exception);
  else if (strcmp(argv[1],"xml") == 0) status=Xml(argc,argv,exception);
  else if (strcmp(argv[1],"blob") == 0) status=Blob(argc,argv,exception);
  else if (strcmp(argv[1],"quantum") == 0) status=QuantumCmd(argc,argv,exception);
  else if (strcmp(argv[1],"matrix") == 0) status=MatrixCmd(argc,argv,exception);
  else if (strcmp(argv[1],"resample") == 0) status=ResampleCmd(argc,argv,exception);
  else if (strcmp(argv[1],"glob") == 0) status=GlobCmd(argc,argv,exception);
  else if (strcmp(argv[1],"tokenize") == 0) status=TokenizeCmd(argc,argv,exception);
  else if (strcmp(argv[1],"color") == 0) status=ColorCmd(argc,argv,exception);
  else if (strcmp(argv[1],"stream") == 0) status=StreamCmd(argc,argv,exception);
  else if (strcmp(argv[1],"cache") == 0) status=CacheCmd(argc,argv,exception);
  else if (strcmp(argv[1],"blobio") == 0) status=BlobIOCmd(argc,argv,exception);
  else if (strcmp(argv[1],"string") == 0) status=StringCmd(argc,argv,exception);
  else if (strcmp(argv[1],"symlink") == 0) status=SymlinkCmd(argc,argv,exception);
  else if (strcmp(argv[1],"metrics") == 0) status=MetricsCmd(argc,argv,exception);
  else if (strcmp(argv[1],"memory") == 0) status=MemoryCmd(argc,argv,exception);
  else if (strcmp(argv[1],"pathauth") == 0) status=PathAuthCmd(argc,argv,exception);
  else if (strcmp(argv[1],"nextimage") == 0) status=NextImageCmd(argc,argv,exception);
  else if (strcmp(argv[1],"configure") == 0) status=ConfigureCmd(argc,argv,exception);
  else if (strcmp(argv[1],"logcfg") == 0) status=LogCfgCmd(argc,argv,exception);
  else if (strcmp(argv[1],"mimecfg") == 0) status=MimeCfgCmd(argc,argv,exception);
  else if (strcmp(argv[1],"delegatecfg") == 0) status=DelegateCfgCmd(argc,argv,exception);
  else if (strcmp(argv[1],"selfkill") == 0) { (void) raise(SIGKILL); status=0; }
  else if (strcmp(argv[1],"drawinfo") == 0) status=DrawInfoCmd(argc,argv,exception);
  else { (void) fprintf(stderr,"unknown command %s\n",argv[1]); status=2; }
  exception=DestroyExceptionInfo(exception);
  MagickCoreTerminus();
  return(status);
}
