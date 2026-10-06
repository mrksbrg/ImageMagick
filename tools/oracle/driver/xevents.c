/*
  xevents SCRIPT -- COMMAND [ARGS...]: run an X client and drive it with synthetic key presses
  (XTEST), for the oracle's interactive X11 cases (display's commands and widgets).

  SCRIPT is a list of space-separated actions, run in order:
    map           wait for a new top-level window to be mapped, then give it the focus
    key:NAME      press a key (an X keysym name: q, slash, F7, Return; ctrl+s, shift+Tab);
                  key:NAME*N presses it N times
    type:TEXT     type TEXT, one key per character ('_' stands for a space)
    point:X,Y     move the pointer to X,Y in the focused window (widgets read the pointer)
    click:X,Y     move it there and click the first button
    press:X,Y     move it there and press the first button (held until release:)
    move:X,Y      move it there, the button still held (display's crop, ROI and draw modes
                  follow the pointer while the button is down)
    release:X,Y   move it there and release the first button
    drag:X1,Y1,X2,Y2[,N]
                  press at X1,Y1, move to X2,Y2 in N steps (default 4), release there
    use:N         keep the focus on the Nth window waited for (1: the first) until the next map,
                  e.g. the image window while display's Commands widget stays open
    grab:FILE     write the focused window's pixels as PPM (24-bit TrueColor screens)
  After every key the helper waits until the client is idle: blocked in poll or select with
  nothing unread on its X connection (pidfd_getfd + FIONREAD), so the case does not depend on
  how fast the machine is. At the end it waits for the client to exit; a client that is still
  running after 20 s is killed, and the helper exits with 124.
*/
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/sockios.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <X11/XKBlib.h>
#include <X11/extensions/XTest.h>

static Display *dpy;
static pid_t child;
static int pidfd = -1, xfd = -1;
static Window focus = None, mapped[64];
static int nmapped = 0, pinned = -1;

static void Nap(long ms)
{
  struct timespec t = { ms / 1000, (ms % 1000) * 1000000L };
  nanosleep(&t, NULL);
}

static double Now(void)
{
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}

static void Fail(const char *what)
{
  fprintf(stderr, "xevents: %s\n", what);
  if (child > 0) kill(child, SIGKILL);
  exit(125);
}

/* The client's file descriptor for its X connection, duplicated into this process. */
static void FindXSocket(void)
{
  char path[64];
  DIR *d;
  struct dirent *e;
  if (pidfd < 0) pidfd = (int) syscall(SYS_pidfd_open, child, 0);
  if (pidfd < 0) Fail("pidfd_open");
  snprintf(path, sizeof(path), "/proc/%d/fd", (int) child);
  if ((d = opendir(path)) == NULL) return;
  while ((e = readdir(d)) != NULL)
  {
    int fd = atoi(e->d_name), dup;
    struct sockaddr_un peer;
    socklen_t len = sizeof(peer);
    if (e->d_name[0] == '.') continue;
    dup = (int) syscall(SYS_pidfd_getfd, pidfd, fd, 0);
    if (dup < 0) continue;
    memset(&peer, 0, sizeof(peer));
    if ((getpeername(dup, (struct sockaddr *) &peer, &len) == 0) && (peer.sun_family == AF_UNIX) &&
        (memmem(peer.sun_path, len - sizeof(peer.sun_family), ".X11-unix/X", 11) != NULL))
      { xfd = dup; break; }
    close(dup);
  }
  closedir(d);
}

/* Blocked in poll/select (or exited) with nothing unread on its X connection and nothing it
   wrote still waiting for the server to read. */
static int Idle(void)
{
  char path[64], buf[64];
  FILE *f;
  long nr = -1;
  int unread = 0;
  snprintf(path, sizeof(path), "/proc/%d/syscall", (int) child);
  if ((f = fopen(path, "r")) == NULL) return 1;  /* gone */
  if (fgets(buf, sizeof(buf), f) != NULL) nr = strtol(buf, NULL, 10);
  fclose(f);
  if ((nr != SYS_poll) && (nr != SYS_ppoll) && (nr != SYS_select) && (nr != SYS_pselect6)) return 0;
  if (xfd < 0) FindXSocket();
  if ((xfd >= 0) && (ioctl(xfd, FIONREAD, &unread) == 0) && (unread > 0)) return 0;
  if ((xfd >= 0) && (ioctl(xfd, SIOCOUTQ, &unread) == 0) && (unread > 0)) return 0;
  return 1;
}

static void WaitIdle(void)
{
  double end = Now() + 20;
  int calm = 0;
  XSync(dpy, False);
  while (calm < 4)  /* four looks in a row, 10 ms apart */
  {
    if (Now() > end) Fail("client never became idle");
    calm = Idle() ? calm + 1 : 0;
    Nap(10);
  }
}

/* display makes and destroys short-lived windows: one may vanish between XQueryTree and
   XGetWindowAttributes. Xlib's default handler would exit on that BadWindow. */
static int IgnoreError(Display *d, XErrorEvent *e)
{
  (void) d; (void) e;
  return 0;
}

static int Viewable(Window w)
{
  XWindowAttributes a;
  return XGetWindowAttributes(dpy, w, &a) && (a.map_state == IsViewable);
}

/* Focus the newest window this script waited for that is still mapped: a dialog while it is
   open, the window under it once it closes. No window manager does this here. */
static void Refocus(void)
{
  int i;
  for (i = nmapped - 1; i >= 0; i--)
    if (((pinned < 0) || (i == pinned)) && Viewable(mapped[i]))
    {
      if (mapped[i] != focus)
      {
        XWindowAttributes a;
        focus = mapped[i];
        XGetWindowAttributes(dpy, focus, &a);
        XWarpPointer(dpy, None, focus, 0, 0, 0, 0, a.width / 2, a.height / 2);
        XSetInputFocus(dpy, focus, RevertToPointerRoot, CurrentTime);
        XSync(dpy, False);
      }
      return;
    }
}

/* Wait for the next top-level window to be mapped (a MapNotify on the root, which this client
   selects before the client starts: widget.c maps the same window as a menu, then as a dialog),
   one still mapped once the client is idle, and focus it. */
static void Map(void)
{
  double end = Now() + 20;
  for (;;)
  {
    while (XPending(dpy))
    {
      XEvent e;
      XNextEvent(dpy, &e);
      if ((e.type == MapNotify) && (e.xmap.event == DefaultRootWindow(dpy)))
      {
        Window w = e.xmap.window;
        WaitIdle();  /* a window still mapped once the client is idle, not a passing one */
        if (Viewable(w))
        {
          if (nmapped < 64) mapped[nmapped++] = w;
          pinned = -1;
          Refocus();
          WaitIdle();
          return;
        }
      }
    }
    if (Now() > end) Fail("no new window");
    Nap(10);
    XSync(dpy, False);
  }
}

static void Press(KeySym sym, int shift, int ctrl)
{
  KeyCode code = XKeysymToKeycode(dpy, sym);
  KeyCode sh = XKeysymToKeycode(dpy, XK_Shift_L), ct = XKeysymToKeycode(dpy, XK_Control_L);
  if (code == 0) Fail("no keycode for a key");
  Refocus();
  if (XkbKeycodeToKeysym(dpy, code, 0, 1) == sym && XkbKeycodeToKeysym(dpy, code, 0, 0) != sym) shift = 1;
  if (ctrl) XTestFakeKeyEvent(dpy, ct, True, CurrentTime);
  if (shift) XTestFakeKeyEvent(dpy, sh, True, CurrentTime);
  XTestFakeKeyEvent(dpy, code, True, CurrentTime);
  XTestFakeKeyEvent(dpy, code, False, CurrentTime);
  if (shift) XTestFakeKeyEvent(dpy, sh, False, CurrentTime);
  if (ctrl) XTestFakeKeyEvent(dpy, ct, False, CurrentTime);
  WaitIdle();
}

static void Key(const char *arg)
{
  int shift = 0, ctrl = 0, times = 1;
  char spec[64], *star;
  snprintf(spec, sizeof(spec), "%s", arg);
  if ((star = strchr(spec, '*')) != NULL) { times = atoi(star + 1); *star = 0; }
  char *name = spec;
  for (;;)
  {
    if (strncmp(name, "ctrl+", 5) == 0) { ctrl = 1; name += 5; }
    else if (strncmp(name, "shift+", 6) == 0) { shift = 1; name += 6; }
    else break;
  }
  KeySym sym = XStringToKeysym(name);
  if (sym == NoSymbol) Fail("unknown key name");
  while (times-- > 0)
    Press(sym, shift, ctrl);
}

static void Type(const char *text)
{
  for (; *text; text++)
  {
    char name[2] = { *text == '_' ? ' ' : *text, 0 };
    KeySym sym = (name[0] == ' ') ? XK_space : XStringToKeysym(name);
    if (sym == NoSymbol) sym = (KeySym) (unsigned char) name[0];
    Press(sym, 0, 0);
  }
}

static int SameImage(XImage *a, XImage *b)
{
  return a && b && (a->width == b->width) && (a->height == b->height) &&
    (a->bytes_per_line == b->bytes_per_line) &&
    (memcmp(a->data, b->data, (size_t) a->height * a->bytes_per_line) == 0);
}

/* The server may not yet have drawn (or resized) what the idle client sent it, so the window is
   read, size and pixels, until four reads in a row, 30 ms apart, agree (the server may still owe the client an Expose). */
static void Point(const char *xy)
{
  int x = 0, y = 0;
  if (sscanf(xy, "%d,%d", &x, &y) != 2) Fail("point:X,Y");
  Refocus();
  XWarpPointer(dpy, None, focus, 0, 0, 0, 0, x, y);
  WaitIdle();
}

/* The first button down or up at X,Y in the focused window; the pointer is moved there first. */
static void Button(const char *xy, Bool down)
{
  Point(xy);
  XTestFakeButtonEvent(dpy, 1, down, CurrentTime);
  WaitIdle();
}

static void Drag(const char *arg)
{
  int x1, y1, x2, y2, n = 4, i;
  char xy[64];
  if (sscanf(arg, "%d,%d,%d,%d,%d", &x1, &y1, &x2, &y2, &n) < 4) Fail("drag:X1,Y1,X2,Y2[,N]");
  if (n < 1) n = 1;
  (void) snprintf(xy, sizeof(xy), "%d,%d", x1, y1);
  Button(xy, True);
  for (i = 1; i <= n; i++)
  {
    (void) snprintf(xy, sizeof(xy), "%d,%d", x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n);
    Point(xy);
  }
  Button(xy, False);
}

static void Grab(const char *file)
{
  XWindowAttributes a;
  XImage *im = NULL, *last = NULL;
  FILE *f;
  int x, y, same = 0;
  double end = Now() + 20;
  Refocus();
  if ((focus == None) || !XGetWindowAttributes(dpy, focus, &a)) Fail("nothing to grab");
  while (same < 3)
  {
    if (Now() > end) Fail("the window never settled");
    WaitIdle();
    Nap(30);
    if (!XGetWindowAttributes(dpy, focus, &a)) Fail("the window went away");
    im = XGetImage(dpy, focus, 0, 0, a.width, a.height, AllPlanes, ZPixmap);
    if (im == NULL) { same = 0; continue; }  /* resized between the two requests */
    same = SameImage(im, last) ? same + 1 : 0;
    if (last) XDestroyImage(last);
    last = im;
  }
  if ((f = fopen(file, "wb")) == NULL) Fail("cannot write the grab");
  fprintf(f, "P6\n%d %d\n255\n", im->width, im->height);
  for (y = 0; y < im->height; y++)
    for (x = 0; x < im->width; x++)
    {
      unsigned long p = XGetPixel(im, x, y);
      fputc((int) ((p >> 16) & 0xff), f); fputc((int) ((p >> 8) & 0xff), f); fputc((int) (p & 0xff), f);
    }
  fclose(f);
  XDestroyImage(im);
  (void) last;
}

int main(int argc, char **argv)
{
  int i, sep = -1, status = 0, ev, er, mj, mn;
  double end;
  for (i = 1; i < argc; i++) if (strcmp(argv[i], "--") == 0) { sep = i; break; }
  if ((sep < 2) || (sep + 1 >= argc)) { fprintf(stderr, "usage: xevents SCRIPT -- COMMAND [ARGS...]\n"); return 2; }
  if ((dpy = XOpenDisplay(NULL)) == NULL) { fprintf(stderr, "xevents: no X server\n"); return 125; }
  if (!XTestQueryExtension(dpy, &ev, &er, &mj, &mn)) Fail("no XTEST");
  XSetErrorHandler(IgnoreError);
  XSelectInput(dpy, DefaultRootWindow(dpy), SubstructureNotifyMask);
  XSync(dpy, False);
  fflush(stdout);
  if ((child = fork()) == 0) { execv(argv[sep + 1], argv + sep + 1); _exit(127); }
  for (i = 1; i < sep; i++)
  {
    char *script = strdup(argv[i]), *save = NULL, *tok;
    for (tok = strtok_r(script, " ", &save); tok; tok = strtok_r(NULL, " ", &save))
    {
      if (strcmp(tok, "map") == 0) Map();
      else if (strncmp(tok, "key:", 4) == 0) Key(tok + 4);
      else if (strncmp(tok, "type:", 5) == 0) Type(tok + 5);
      else if (strncmp(tok, "grab:", 5) == 0) Grab(tok + 5);
      else if (strncmp(tok, "point:", 6) == 0) Point(tok + 6);
      else if (strncmp(tok, "use:", 4) == 0) { pinned = atoi(tok + 4) - 1; Refocus(); }
      else if (strncmp(tok, "click:", 6) == 0) { Point(tok + 6); XTestFakeButtonEvent(dpy, 1, True, CurrentTime);
        XTestFakeButtonEvent(dpy, 1, False, CurrentTime); WaitIdle(); }
      else if (strncmp(tok, "press:", 6) == 0) Button(tok + 6, True);
      else if (strncmp(tok, "move:", 5) == 0) Point(tok + 5);
      else if (strncmp(tok, "release:", 8) == 0) Button(tok + 8, False);
      else if (strncmp(tok, "drag:", 5) == 0) Drag(tok + 5);
      else Fail("unknown action");
    }
    free(script);
  }
  end = Now() + 20;
  while (waitpid(child, &status, WNOHANG) == 0)
  {
    if (Now() > end) { kill(child, SIGKILL); waitpid(child, &status, 0); return 124; }
    Nap(10);
  }
  return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
