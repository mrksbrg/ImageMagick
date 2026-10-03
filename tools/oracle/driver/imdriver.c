/*
  imdriver: calls MagickCore functions the command line cannot reach, for the oracle.

    imdriver gradient TYPE SPREAD WxH [ARTIFACT=VALUE...] COLOR:OFFSET... OUT
    imdriver mask KIND IMAGE MASK OPERATION OUT     (KIND read|write|composite)
    imdriver getmask KIND IMAGE MASK OUT
    imdriver acquire KEY=VALUE...                   (ImageInfo fields, then AcquireImage)
    imdriver list policy|locale|mime PATTERN
    imdriver mime FILE

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
  else { (void) fprintf(stderr,"unknown command %s\n",argv[1]); status=2; }
  exception=DestroyExceptionInfo(exception);
  MagickCoreTerminus();
  return(status);
}
