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

  It is linked against the build under test (build.sh), so a mutant switched on in the
  environment is active here as in magick. Output goes to stdout or to the named file.
*/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "MagickCore/studio.h"
#include "MagickCore/MagickCore.h"

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

int main(int argc,char **argv)
{
  ExceptionInfo *exception;
  int status;

  if (argc < 2)
    {
      (void) fprintf(stderr,"imdriver gradient|mask|getmask|acquire|list|mime ...\n");
      return(2);
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
  else { (void) fprintf(stderr,"unknown command %s\n",argv[1]); status=2; }
  exception=DestroyExceptionInfo(exception);
  MagickCoreTerminus();
  return(status);
}
