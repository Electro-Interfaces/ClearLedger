/* SOURCE ONLY / NOTRUN. No build or kernel control was run to produce this file.
 * Trusted Linux/x86_64 broker, not a setuid installation. Invoke only through a
 * separately reviewed privileged controller with independently pinned inputs.
 * Kernel/CPython compatibility and every security control require ROOT tests.
 */
#define _GNU_SOURCE
#include "launcher_protocol.h"
#include <asm/unistd.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <linux/audit.h>
#include <linux/capability.h>
#include <linux/filter.h>
#include <linux/sched.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/time.h>
#include <sys/vfs.h>
#include <sys/mount.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/timerfd.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#if !defined(__x86_64__) || defined(__ILP32__)
#error Only native Linux x86_64 LP64 is supported
#endif

/* A small native SHA-256 implementation: no dynamic crypto provider or child
 * command is part of the trusted launcher. All lengths are bounded by callers.
 */
typedef struct { uint32_t h[8]; uint64_t n; unsigned used; unsigned char b[64]; } Sha;
static uint32_t rr(uint32_t v,unsigned n){return(v>>n)|(v<<(32-n));}
static void shablock(Sha*s,const unsigned char*b){
 static const uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
 uint32_t w[64],a=s->h[0],c=s->h[2],b0=s->h[1],d=s->h[3],e=s->h[4],f=s->h[5],g=s->h[6],h=s->h[7];
 for(unsigned i=0;i<16;i++)w[i]=((uint32_t)b[4*i]<<24)|((uint32_t)b[4*i+1]<<16)|((uint32_t)b[4*i+2]<<8)|b[4*i+3];
 for(unsigned i=16;i<64;i++)w[i]=w[i-16]+(rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>10));
 for(unsigned i=0;i<64;i++){uint32_t t=h+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^(~e&g))+k[i]+w[i];uint32_t u=(rr(a,2)^rr(a,13)^rr(a,22))+((a&b0)^(a&c)^(b0&c));h=g;g=f;f=e;e=d+t;d=c;c=b0;b0=a;a=t+u;}
 s->h[0]+=a;s->h[1]+=b0;s->h[2]+=c;s->h[3]+=d;s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;
}
static void shainit(Sha*s){*s=(Sha){.h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};}
static void shaup(Sha*s,const void*p,size_t n){const unsigned char*b=p;s->n+=n;while(n){size_t q=64-s->used;if(q>n)q=n;memcpy(s->b+s->used,b,q);s->used+=(unsigned)q;b+=q;n-=q;if(s->used==64){shablock(s,s->b);s->used=0;}}}
static void shafinal(Sha*s,char out[65]){uint64_t bits=s->n*8;unsigned char one=0x80,zero=0;shaup(s,&one,1);while(s->used!=56)shaup(s,&zero,1);unsigned char b[8];for(unsigned i=0;i<8;i++)b[i]=(unsigned char)(bits>>(56-8*i));shaup(s,b,8);for(unsigned i=0;i<8;i++)snprintf(out+8*i,9,"%08x",s->h[i]);out[64]=0;}
static void hashbytes(const void*p,size_t n,char out[65]){Sha s;shainit(&s);shaup(&s,p,n);shafinal(&s,out);}

typedef struct {char b[DX_FRAME_MAX+1];size_t n;} Json;
typedef struct {unsigned char*b;size_t n,p;} Reader;
static char cfg[DX_CONFIG_FIELDS][4096];
static uid_t uid;static gid_t gid;
static int child_channel=-1,pidfd=-1,storagefd=-1,poolfd=-1,cgroupfd=-1,writer=-1;
static pid_t childpid=-1;
static atomic_int rejected=0,watch_stop=0;
static atomic_ullong wall_deadline=0;
static pthread_mutex_t sample_lock=PTHREAD_MUTEX_INITIALIZER;
static uint64_t before_free,minimum_free,after_free,sample_ms,maxgap,samples;
static uint32_t inseq=0,outseq=0;
static uint64_t output_bytes=0;
static uint64_t metadata_bytes=0;
static const uint64_t reserve_sizes[4]={DX_OUTPUT_MAX,4ULL*1024*1024,DX_RECEIPT_MAX,DX_RECEIPT_MAX};
static const uint64_t reserve_bytes=DX_OUTPUT_MAX+4ULL*1024*1024+2ULL*DX_RECEIPT_MAX;
static int reserves[4]={-1,-1,-1,-1};
static struct stat python_stat;
static char controller_ns[6][32];
static char ready_mount_hash[65];
static const char*nsnames[]={"mnt","net","pid","ipc","user","time"};
static void record_meta(unsigned op,const void*p,size_t n);
static uint64_t nowms(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))_exit(120);return(uint64_t)t.tv_sec*1000+(uint64_t)t.tv_nsec/1000000;}
static void killreject(void){atomic_store(&rejected,1);if(pidfd>=0)(void)syscall(SYS_pidfd_send_signal,pidfd,SIGKILL,NULL,0);}
static void fatal(const char*why){
 killreject();
 /* write is in the bootstrap filter; send/sendto deliberately are not. */
 if(child_channel>=0)(void)write(child_channel,why,strlen(why));
 (void)write(2,why,strlen(why));(void)write(2,"\n",1);
 _exit(120);
}
#define NEED(x,msg) do{if(!(x))fatal(msg);}while(0)
static uint32_t le32(const unsigned char*p){return(uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void put32(unsigned char*p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static uint32_t ru32(Reader*r){NEED(r->n-r->p>=4,"truncated u32");uint32_t n=le32(r->b+r->p);r->p+=4;return n;}
static void rstr(Reader*r,char*out,size_t cap){uint32_t n=ru32(r);NEED(n>0&&n<cap&&n<=r->n-r->p,"LP string length");for(unsigned i=0;i<n;i++)NEED(r->b[r->p+i]>=32&&r->b[r->p+i]<127,"LP ASCII");memcpy(out,r->b+r->p,n);out[n]=0;r->p+=n;}
static void ioall(int fd,void*buf,size_t n,bool writing){unsigned char*p=buf;while(n){NEED(!atomic_load(&rejected),"watchdog rejected");struct pollfd f={fd,writing?POLLOUT:POLLIN,0};int q=poll(&f,1,100);if(q<0&&errno==EINTR)continue;NEED(q>=0,"protocol poll");if(!q)continue;NEED(!(f.revents&(POLLERR|POLLNVAL)),"protocol fd failure");ssize_t k=writing?write(fd,p,n):read(fd,p,n);if(k<0&&(errno==EINTR||errno==EAGAIN))continue;NEED(k>0,"protocol EOF/backpressure failure");p+=k;n-=(size_t)k;}}
static void frame(unsigned op,const void*p,size_t n){NEED(n<=DX_FRAME_MAX&&outseq<UINT32_MAX,"outgoing frame bound");if(op!=DX_STDOUT&&op!=DX_STDERR)record_meta(op,p,n);unsigned char h[16]={ 'D','X','K','1',1,0,0,0 };h[6]=(unsigned char)op;put32(h+8,(uint32_t)n);put32(h+12,++outseq);ioall(1,h,16,true);ioall(1,(void*)p,n,true);}
static Reader receive(unsigned want){unsigned char h[16];ioall(0,h,16,false);NEED(!memcmp(h,DX_MAGIC,4)&&h[4]==1&&!h[5]&&!h[7],"wire magic/version");NEED(h[6]==want&&inseq<UINT32_MAX&&le32(h+12)==++inseq,"wire opcode/sequence");uint32_t n=le32(h+8);NEED(n>0&&n<=DX_FRAME_MAX,"wire payload bound");unsigned char*b=malloc(n+1);NEED(b,"wire allocation");ioall(0,b,n,false);b[n]=0;return(Reader){b,n,0};}
static void jadd(Json*j,const char*f,...){va_list a;va_start(a,f);int n=vsnprintf(j->b+j->n,sizeof(j->b)-j->n,f,a);va_end(a);NEED(n>=0&&(size_t)n<sizeof(j->b)-j->n,"JSON bound");j->n+=(size_t)n;}
static void jq(Json*j,const char*s){jadd(j,"\"");for(const unsigned char*p=(const unsigned char*)s;*p;p++){NEED(*p<128,"JSON ASCII");if(*p=='"'||*p=='\\')jadd(j,"\\%c",*p);else if(*p=='\n')jadd(j,"\\n");else if(*p=='\r')jadd(j,"\\r");else if(*p=='\t')jadd(j,"\\t");else if(*p<32)jadd(j,"\\u%04x",*p);else jadd(j,"%c",*p);}jadd(j,"\"");}
static void jb64(Json*j,const char*s){
 static const char t[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
 size_t n=strlen(s);jadd(j,"\"");
 for(size_t i=0;i<n;i+=3){unsigned a=(unsigned char)s[i],b=i+1<n?(unsigned char)s[i+1]:0,c=i+2<n?(unsigned char)s[i+2]:0;
  jadd(j,"%c%c%c%c",t[a>>2],t[((a&3)<<4)|(b>>4)],i+1<n?t[((b&15)<<2)|(c>>6)]:'=',i+2<n?t[c&63]:'=');}
 jadd(j,"\"");
}
static void jsonframe(unsigned op,Json*j){jadd(j,"\n");frame(op,j->b,j->n);}
static uint64_t decimal(const char*s){NEED(*s&&(!(*s=='0'&&s[1])),"canonical decimal");uint64_t n=0;for(;*s;s++){NEED(*s>='0'&&*s<='9'&&n<=(UINT64_MAX-9)/10,"decimal bound");n=n*10+(*s-'0');}return n;}
static bool hexstr(const char*s,size_t n){if(strlen(s)!=n)return false;for(size_t i=0;i<n;i++)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return false;return true;}
static void pathcheck(const char*p){
 NEED(p[0]=='/'&&strlen(p)<4096,"absolute path");
 NEED(!strstr(p,"//")&&!strstr(p,"/../")&&!strstr(p,"/./"),"normalized path");
 size_t n=strlen(p);
 NEED(n==1||p[n-1]!='/',"path trailing slash");
 NEED(strcmp(p,"/.")&&strcmp(p,"/..")&&(n<2||strcmp(p+n-2,"/."))&&(n<3||strcmp(p+n-3,"/..")),"dot path components");
 char s[4096];memcpy(s,p,n+1);
 for(size_t i=1;i<=n;i++){
  char c=s[i];
  if(c=='/'||!c){
   s[i]=0;struct stat st;
   NEED(!lstat(s,&st)&&!S_ISLNK(st.st_mode),"path component symlink/missing");s[i]=c;
  }else NEED((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='.'||c=='_'||c=='-',"path grammar");
 }
}
static void hashfd(int fd,char out[65],uint64_t limit){NEED(lseek(fd,0,SEEK_SET)==0,"hash seek");Sha s;shainit(&s);unsigned char b[16384];uint64_t n=0;for(;;){ssize_t q=read(fd,b,sizeof(b));if(q<0&&errno==EINTR)continue;NEED(q>=0,"hash read");if(!q)break;n+=(uint64_t)q;NEED(n<=limit,"hash byte bound");shaup(&s,b,(size_t)q);}shafinal(&s,out);NEED(lseek(fd,0,SEEK_SET)==0,"hash rewind");}
static void hashfile(const char*p,const char*expected,uint64_t limit){int fd=open(p,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);NEED(fd>=0,"pinned open");struct stat s;NEED(!fstat(fd,&s)&&S_ISREG(s.st_mode)&&s.st_nlink==1,"pinned regular single link");char h[65];hashfd(fd,h,limit);NEED(!strcmp(h,expected),"independent pin mismatch");NEED(!close(fd),"pinned close");}
static char*readfixed(const char*p,size_t limit){int fd=open(p,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);NEED(fd>=0,"fixed read open");char*b=calloc(limit+2,1);NEED(b,"fixed read allocation");size_t n=0;while(n<=limit){ssize_t k=read(fd,b+n,limit+1-n);if(k<0&&errno==EINTR)continue;NEED(k>=0,"fixed read");if(!k)break;n+=(size_t)k;}NEED(n>0&&n<=limit,"fixed read bound");NEED(!close(fd),"fixed read close");return b;}
static void nsread(const char*prefix,const char*name,char out[32]){char p[4096],b[128];NEED(snprintf(p,sizeof(p),"%s/ns/%s",prefix,name)<(int)sizeof(p),"ns path");ssize_t n=readlink(p,b,sizeof(b)-1);NEED(n>0&&(size_t)n<sizeof(b)-1,"ns readlink");b[n]=0;char fmt[64];snprintf(fmt,sizeof(fmt),"%s:[%%31[0-9]]]",name);NEED(sscanf(b,fmt,out)==1&&decimal(out)>0,"namespace inode");}

/* All namespace mounts are complete before filtered bootstrap measurement.
 * Nonrecursive binds deliberately do not inherit host nested mounts. The rootfs
 * must already contain every destination and .oldroot, including passwd HOME.
 */
static void dest(char out[8192],const char*p){NEED(snprintf(out,8192,"%s%s",cfg[DX_ROOTFS],p)<8192,"mount target bound");}
static void bindro(const char*src,const char*guest){
 char d[8192];dest(d,guest);pathcheck(src);pathcheck(d);
 NEED(!mount(src,d,NULL,MS_BIND,NULL),"bind input");
 NEED(!mount(NULL,d,NULL,MS_BIND|MS_REMOUNT|MS_RDONLY|MS_NOSUID|MS_NODEV,NULL),"RO bind input");
}
static void mount_setup(void){
 NEED(!mount(NULL,"/",NULL,MS_REC|MS_PRIVATE,NULL),"private propagation");
 NEED(!mount(cfg[DX_ROOTFS],cfg[DX_ROOTFS],NULL,MS_BIND,NULL),"rootfs bind");
 bindro(cfg[DX_SOURCE],cfg[DX_SOURCE]);
 bindro(cfg[DX_NATIVE],cfg[DX_NATIVE]);
 bindro(cfg[DX_VENV],cfg[DX_VENV]);
 /* Source is a .git-free snapshot. Git identity is verified only outside. */
 char cacheparent[4096];strcpy(cacheparent,cfg[DX_CACHE_HOST]);
 char*slash=strrchr(cacheparent,'/');NEED(slash&&slash!=cacheparent,"cache parent");*slash=0;
 char guestparent[4096];strcpy(guestparent,cfg[DX_CACHE_GUEST]);
 char*guestslash=strrchr(guestparent,'/');NEED(guestslash&&guestslash!=guestparent,"guest cache parent");*guestslash=0;
 bindro(cacheparent,guestparent);
 char policyparent[4096];strcpy(policyparent,cfg[DX_POLICY_HOST]);
 *strrchr(policyparent,'/')=0;bindro(policyparent,"/inputs/policy");
 char admissionparent[4096];strcpy(admissionparent,cfg[DX_ADMISSION_HOST]);
 *strrchr(admissionparent,'/')=0;bindro(admissionparent,"/inputs/admission");
 char d[8192];dest(d,cfg[DX_POOL]);pathcheck(d);
 NEED(!mount("dx-work",d,"tmpfs",MS_NOSUID|MS_NODEV|MS_NOEXEC,
             "size=67108864,nr_inodes=133,mode=0755,uid=0,gid=0"),"shared tmpfs");
 const char*dirs[]={"cwd","upload","evidence","scratch"};
 for(unsigned i=0;i<4;i++){
  char q[8192];NEED(snprintf(q,sizeof(q),"%s/%s",d,dirs[i])<(int)sizeof(q),"work path");
  NEED(!mkdir(q,0700),"create work directory");
  NEED(!chown(q,uid,gid)&&!chmod(q,0700),"private work directory identity");
  if(i<2){
   NEED(!mount(q,q,NULL,MS_BIND,NULL),"work self bind");
   NEED(!mount(NULL,q,NULL,MS_REMOUNT|MS_BIND|MS_RDONLY|MS_NOSUID|MS_NODEV|MS_NOEXEC,NULL),"cwd/upload RO");
  }
 }
 dest(d,"/proc");pathcheck(d);
 NEED(!mount("proc",d,"proc",MS_RDONLY|MS_NOSUID|MS_NODEV|MS_NOEXEC,NULL),"fresh RO proc");
 char old[8192];dest(old,"/.oldroot");pathcheck(old);
 NEED(!syscall(SYS_pivot_root,cfg[DX_ROOTFS],old),"pivot root");
 NEED(!chdir("/"),"new cwd");
 NEED(!umount2("/.oldroot",MNT_DETACH),"detach old root");
 NEED(!mount(NULL,"/",NULL,MS_REMOUNT|MS_BIND|MS_RDONLY|MS_NOSUID|MS_NODEV,NULL),"RO rootfs");
}
static void limits_and_identity(void){
 const int resources[]={RLIMIT_CPU,RLIMIT_AS,RLIMIT_FSIZE,RLIMIT_CORE,RLIMIT_NOFILE};
 const rlim_t vals[]={150,DX_MEMORY_MAX,DX_FILE_MAX,0,96};
 for(unsigned i=0;i<5;i++){
  struct rlimit r={vals[i],vals[i]};
  NEED(!setrlimit(resources[i],&r),"kernel rlimit");
 }
 char*cap=readfixed("/proc/sys/kernel/cap_last_cap",32);
 int last=(int)strtol(cap,NULL,10);free(cap);
 NEED(last>=CAP_LAST_CAP&&last<64,"capability range");
 for(int c=0;c<=last;c++)NEED(!prctl(PR_CAPBSET_DROP,c,0,0,0),"drop bounding capability");
 NEED(!prctl(PR_CAP_AMBIENT,PR_CAP_AMBIENT_CLEAR_ALL,0,0,0),"clear ambient capabilities");
 NEED(!setgroups(0,NULL),"empty supplementary groups");
 NEED(!setresgid(gid,gid,gid),"drop exact gid");
 NEED(!setresuid(uid,uid,uid),"drop exact uid");
 struct __user_cap_header_struct h={_LINUX_CAPABILITY_VERSION_3,0};
 struct __user_cap_data_struct d[2]={{0},{0}};
 NEED(!syscall(SYS_capset,&h,d),"clear capability sets");
 NEED(!prctl(PR_SET_DUMPABLE,0,0,0,0),"non dumpable bootstrap");
 NEED(!prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0),"no new privileges");
 uid_t r,e,s;gid_t gr,ge,gs;
 NEED(!getresuid(&r,&e,&s)&&r==uid&&e==uid&&s==uid,"uid tuple");
 NEED(!getresgid(&gr,&ge,&gs)&&gr==gid&&ge==gid&&gs==gid&&getgroups(0,NULL)==0,"gid/groups tuple");
}

/* Policy digest binds the reviewed JSON to exactly the compiled allowlist.
 * Updated together; no runtime policy parser, dynamic profiles or fallback.
 */
#define POLICY_SHA "330fb9a4353ea0f922664858c12b4b6d4aae602e5ebc4835e294e658c1f3822f"
static const unsigned allowed[]={0,1,3,4,5,6,7,8,9,10,11,12,13,14,15,17,19,20,21,24,25,28,32,33,35,39,60,63,72,74,75,76,77,79,80,81,82,83,84,85,87,89,90,91,95,96,97,98,99,102,104,107,108,110,115,118,120,121,137,138,158,186,202,217,218,228,229,230,231,234,257,258,262,263,264,267,268,269,270,271,273,280,290,292,293,318,334,436,439};
static int filter_install(void){struct sock_filter b[512];size_t n=0;
#define STMT(code,k) do{b[n++]=(struct sock_filter)BPF_STMT(code,k);}while(0)
#define JUMP(code,k,t,f) do{b[n++]=(struct sock_filter)BPF_JUMP(code,k,t,f);}while(0)
#define ARGLO(a) (offsetof(struct seccomp_data,args)+(a)*8)
#define ARGHI(a) (ARGLO(a)+4)
 STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,arch));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,AUDIT_ARCH_X86_64,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr));
 JUMP(BPF_JMP|BPF_JSET|BPF_K,0x40000000,0,1);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 /* BOTH exec syscalls notify, regardless of pathname/fd/flags. Outside broker
  * alone consumes the sole initial trusted execveat permission. */
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execve,1,0);
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_execveat,0,1);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_USER_NOTIF);
 /* prlimit64 can repeat only the five pre-lowered legacy hard caps, pid 0.
  * BPF cannot read rlimit pointers: kernel unprivileged hard-cap monotonicity
  * is the enforcement of values, not a claim about pointer contents. */
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_prlimit64,0,17);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGLO(0));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGHI(0));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGHI(1));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGLO(1));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,5,0);
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,1,4,0);
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,4,3,0);
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,7,2,0);
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,9,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW);
 STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_sendmsg,0,13);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGLO(0));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,DX_BOOT_FD,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGHI(0));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGLO(2));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGHI(2));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW);
 STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr));
 /* isatty/stdstream initialization only: exact benign requests, stdio only. */
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_ioctl,0,14);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGHI(0));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGLO(0));
 JUMP(BPF_JMP|BPF_JGT|BPF_K,2,0,1);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGHI(1));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGLO(1));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,TCGETS,2,0);
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,TIOCGWINSZ,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW);
 STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr));
 /* Immutable helper's ITIMER_REAL soft/hard timer remains compatible. The
  * candidate cannot affect the outside watchdog's distinct process timers. */
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_setitimer,0,7);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGLO(0));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,ITIMER_REAL,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_LD|BPF_W|BPF_ABS,ARGHI(0));
 JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW);
 STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr));
 for(size_t i=0;i<sizeof(allowed)/sizeof(*allowed);i++){
  JUMP(BPF_JMP|BPF_JEQ|BPF_K,allowed[i],0,1);
  STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW);
 }
 STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
 NEED(n<512,"BPF instruction bound");
 struct sock_fprog p={(unsigned short)n,b};
 int fd=(int)syscall(SYS_seccomp,SECCOMP_SET_MODE_FILTER,SECCOMP_FILTER_FLAG_NEW_LISTENER,&p);
 NEED(fd>=0,"actual NEW_LISTENER load");return fd;
#undef ARGLO
#undef ARGHI
#undef STMT
#undef JUMP
}

typedef struct {unsigned long id,major,minor;char root[4096],point[4096],type[33],options[2048];bool ro;} Mount;
static Mount*mount_rows;static unsigned mount_count;
static bool below(const char*p,const char*root){size_t n=strlen(root);return!strcmp(p,root)||(!strncmp(p,root,n)&&(n==1||p[n]=='/'));}
static void mounts_parse(const char*raw){mount_rows=calloc(128,sizeof(Mount));NEED(mount_rows,"mount table allocation");char*copy=strdup(raw);NEED(copy,"mount table copy");char*save=NULL;
 for(char*l=strtok_r(copy,"\n",&save);l;l=strtok_r(NULL,"\n",&save)){NEED(mount_count<128,"mount count bound");char*sep=strstr(l," - ");NEED(sep&&!strstr(sep+3," - "),"mountinfo separator");*sep=0;Mount*m=&mount_rows[mount_count++];char flags[1024];unsigned long parent;int used=0;
 NEED(sscanf(l,"%lu %lu %lu:%lu %4095s %4095s %1023s%n",&m->id,&parent,&m->major,&m->minor,m->root,m->point,flags,&used)==7&&m->id>0,"mountinfo fields");
 NEED(!strchr(m->root,'\\')&&!strchr(m->point,'\\'),"mount paths require unescaped normalized ASCII");char source[4096];char extra;
 NEED(sscanf(sep+3,"%32s %4095s %2047s %c",m->type,source,m->options,&extra)==3,"mountinfo suffix");
 m->ro=!strncmp(flags,"ro,",3)||!strcmp(flags,"ro");NEED(m->ro||!strncmp(flags,"rw,",3)||!strcmp(flags,"rw"),"actual mount read flag");
 for(unsigned i=0;i+1<mount_count;i++)NEED(mount_rows[i].id!=m->id,"unique mount id");
 }
 free(copy);NEED(mount_count>0,"nonempty mount table");
}
static Mount*cover(const char*p){Mount*found=NULL;size_t best=0;for(unsigned i=0;i<mount_count;i++){Mount*m=&mount_rows[i];if(below(p,m->point)){size_t n=strlen(m->point);NEED(!found||n!=best,"stacked role mounts unsupported");if(n>best){found=m;best=n;}}}NEED(found,"covering role mount");return found;}
static void mountjson(Json*j,const char*role,const char*p,bool ro){pathcheck(p);Mount*m=cover(p);struct stat s;struct statvfs v;NEED(!stat(p,&s)&&!statvfs(p,&v),"role stat/statvfs");NEED(m->ro==ro&&!!(v.f_flag&ST_RDONLY)==ro&&major(s.st_dev)==m->major&&minor(s.st_dev)==m->minor,"actual role mount binding");
 jadd(j,"{\"fs_type\":");jq(j,m->type);jadd(j,",\"major\":%lu,\"minor\":%lu,\"mode\":\"%04o\",\"mount_id\":%lu,\"mount_point\":",m->major,m->minor,(unsigned)(s.st_mode&07777),m->id);jq(j,m->point);jadd(j,",\"owner_gid\":%u,\"owner_uid\":%u,\"path\":",s.st_gid,s.st_uid);jq(j,p);jadd(j,",\"read_only\":%s,\"role\":",ro?"true":"false");jq(j,role);jadd(j,",\"root\":");jq(j,m->root);jadd(j,"}");
}
static void status_exact(const char*s,const char*field,const char*expected){char*copy=strdup(s);NEED(copy,"status copy");bool seen=false;char*save=NULL;for(char*l=strtok_r(copy,"\n",&save);l;l=strtok_r(NULL,"\n",&save)){char*c=strchr(l,':');if(!c)continue;*c=0;if(strcmp(l,field))continue;NEED(!seen,"duplicate status field");seen=true;c++;while(*c==' '||*c=='\t')c++;NEED(!strcmp(c,expected),"actual status value");}free(copy);NEED(seen,"missing status field");}
static void input_mode(const char*p,mode_t mode){struct stat s;NEED(!lstat(p,&s)&&S_ISREG(s.st_mode)&&s.st_nlink==1&&s.st_uid==uid&&s.st_gid==gid&&(s.st_mode&07777)==mode,"sealed input mode/owner/link");char parent[4096];strcpy(parent,p);*strrchr(parent,'/')=0;NEED(!lstat(parent,&s)&&S_ISDIR(s.st_mode)&&s.st_uid==uid&&s.st_gid==gid&&(s.st_mode&07777)==0700,"sealed parent mode/owner");}
static void singleton_parent(const char*p){
 char parent[4096];strcpy(parent,p);char*name=strrchr(parent,'/');
 NEED(name&&name!=parent,"singleton input parent path");*name++=0;
 DIR*d=opendir(parent);NEED(d,"singleton parent listing");unsigned count=0;struct dirent*e;
 while((e=readdir(d))){
  if(!strcmp(e->d_name,".")||!strcmp(e->d_name,".."))continue;
  NEED(!strcmp(e->d_name,name),"unmeasured input sibling forbidden");count++;
 }
 NEED(!closedir(d)&&count==1,"exact singleton input parent");
}
static void workcheck(void){struct stat root;NEED(!stat(cfg[DX_POOL],&root)&&root.st_uid==0&&(root.st_mode&07777)==0755,"root-owned work pool");DIR*d=opendir(cfg[DX_POOL]);NEED(d,"work pool listing");unsigned n=0;struct dirent*e;while((e=readdir(d))){if(!strcmp(e->d_name,".")||!strcmp(e->d_name,".."))continue;NEED(!strcmp(e->d_name,"cwd")||!strcmp(e->d_name,"upload")||!strcmp(e->d_name,"evidence")||!strcmp(e->d_name,"scratch"),"exact work siblings");n++;}closedir(d);NEED(n==4,"four work siblings");
 const char*names[]={"cwd","upload","evidence","scratch"};for(unsigned i=0;i<4;i++){char p[4096];snprintf(p,sizeof(p),"%s/%s",cfg[DX_POOL],names[i]);struct stat s;NEED(!stat(p,&s)&&s.st_dev==root.st_dev&&s.st_uid==uid&&s.st_gid==gid&&(s.st_mode&07777)==0700,"work identity/device");}
 struct statvfs v;NEED(!statvfs(cfg[DX_POOL],&v)&&v.f_frsize>0&&v.f_blocks>0&&v.f_blocks<=DX_POOL_BYTES/v.f_frsize&&v.f_files>0&&v.f_files<=133,"actual total quota");Mount*m=cover(cfg[DX_POOL]);NEED(!strcmp(m->type,"tmpfs")&&strstr(m->options,"nr_inodes=133")&&(strstr(m->options,"size=65536k")||strstr(m->options,"size=64m")||strstr(m->options,"size=67108864")),"tmpfs explicit finite superoptions");
}
static void listener_send(int fd){
 char b='L';struct iovec i={&b,1};char c[CMSG_SPACE(sizeof(int))]={0};
 struct msghdr m={0};m.msg_iov=&i;m.msg_iovlen=1;
 m.msg_control=c;m.msg_controllen=sizeof(c);
 struct cmsghdr*h=CMSG_FIRSTHDR(&m);
 h->cmsg_level=SOL_SOCKET;h->cmsg_type=SCM_RIGHTS;
 h->cmsg_len=CMSG_LEN(sizeof(int));memcpy(CMSG_DATA(h),&fd,sizeof(fd));
 NEED(sendmsg(DX_BOOT_FD,&m,0)==1,"listener handoff");
 NEED(!close(fd),"close child listener");
}
static int listener_receive(int fd){
 char b=0;struct iovec i={&b,1};char c[CMSG_SPACE(sizeof(int))]={0};
 struct msghdr m={0};m.msg_iov=&i;m.msg_iovlen=1;
 m.msg_control=c;m.msg_controllen=sizeof(c);
 NEED(recvmsg(fd,&m,MSG_CMSG_CLOEXEC)==1&&b=='L'&&!(m.msg_flags&(MSG_TRUNC|MSG_CTRUNC)),"listener handoff frame");
 struct cmsghdr*h=CMSG_FIRSTHDR(&m);
 NEED(h&&h->cmsg_level==SOL_SOCKET&&h->cmsg_type==SCM_RIGHTS&&h->cmsg_len==CMSG_LEN(sizeof(int))&&!CMSG_NXTHDR(&m,h),"exact one listener descriptor");
 int listener;memcpy(&listener,CMSG_DATA(h),sizeof(listener));
 NEED(listener>=0,"listener descriptor");return listener;
}
static void bootwrite(int fd,const void*p,size_t n){ioall(fd,(void*)p,n,true);}
static void bootread(int fd,void*p,size_t n){ioall(fd,p,n,false);}
static void bootstrap_ready(Json*j,uint64_t measured,uint64_t freebytes){char*status=readfixed("/proc/self/status",DX_PROC_MAX);char*mountinfo=readfixed("/proc/self/mountinfo",DX_PROC_MAX);mounts_parse(mountinfo);
 char ids[128];snprintf(ids,sizeof(ids),"%u\t%u\t%u\t%u",uid,uid,uid,uid);status_exact(status,"Uid",ids);snprintf(ids,sizeof(ids),"%u\t%u\t%u\t%u",gid,gid,gid,gid);status_exact(status,"Gid",ids);status_exact(status,"Groups","");status_exact(status,"NoNewPrivs","1");status_exact(status,"Seccomp","2");const char*caps[]={"CapInh","CapPrm","CapEff","CapBnd","CapAmb"};for(unsigned i=0;i<5;i++)status_exact(status,caps[i],"0000000000000000");
 input_mode("/inputs/admission/admission.json",0400);input_mode("/inputs/policy/execute-policy.json",0400);input_mode(cfg[DX_CACHE_GUEST],0600);hashfile("/inputs/policy/execute-policy.json",cfg[DX_POLICY_SHA],DX_FILE_MAX);workcheck();
 jadd(j,"{\"candidate\":{\"cap_amb\":\"0000000000000000\",\"cap_bnd\":\"0000000000000000\",\"cap_eff\":\"0000000000000000\",\"cap_inh\":\"0000000000000000\",\"cap_prm\":\"0000000000000000\",\"gid\":%u,\"home\":",gid);jq(j,cfg[DX_HOME]);jadd(j,",\"no_new_privs\":1,\"seccomp_mode\":2,\"supplementary_gids\":[],\"uid\":%u}",uid);
 jadd(j,",\"controller\":{\"admission_sealed\":true,\"cpu_hard_seconds\":150,\"euid\":0,\"external_watchdog_armed\":true,\"fd_hard_limit\":96,\"file_hard_bytes\":16777216,\"kernel_policy_loaded\":true,\"memory_max_bytes\":2147483648,\"pids_max\":1,\"policy_path\":\"/inputs/policy/execute-policy.json\",\"stdout_stderr_max_bytes\":8388608,\"wall_ms\":180000}");
 jadd(j,",\"host_floor\":{\"after_required\":true,\"before\":[{\"free_bytes\":%llu,\"measured_ms\":%llu,\"storage_id\":",(unsigned long long)freebytes,(unsigned long long)measured);jq(j,cfg[DX_STORAGE_ID]);jadd(j,"}],\"max_sample_gap_ms\":1500,\"monitor_interval_ms\":1000,\"on_failure\":\"KILL_AND_REJECT\",\"threshold_bytes\":8589934592}");
 const char*roles[]={"rootfs","source","native_runtime","venv","policy","admission","cache","work_pool","cwd","upload","evidence","scratch"};char paths[12][4096];const char*base[]={"/",cfg[DX_SOURCE],cfg[DX_NATIVE],cfg[DX_VENV],"/inputs/policy/execute-policy.json","/inputs/admission/admission.json",cfg[DX_CACHE_GUEST],cfg[DX_POOL]};for(unsigned i=0;i<8;i++)strcpy(paths[i],base[i]);const char*names[]={"cwd","upload","evidence","scratch"};for(unsigned i=0;i<4;i++)NEED(snprintf(paths[i+8],sizeof(paths[i+8]),"%s/%s",cfg[DX_POOL],names[i])<(int)sizeof(paths[i+8]),"work path bound");
 jadd(j,",\"mounts\":[");for(unsigned i=0;i<12;i++){if(i)jadd(j,",");mountjson(j,roles[i],paths[i],i!=7&&i!=10&&i!=11);}jadd(j,"]");
 char mhash[65];hashbytes(mountinfo,strlen(mountinfo),mhash);strcpy(ready_mount_hash,mhash);jadd(j,",\"namespaces\":{");const unsigned order[]={3,0,1,2,5,4};for(unsigned k=0;k<6;k++){unsigned i=order[k];if(k)jadd(j,",");jadd(j,"\"controller_%s\":",nsnames[i]);jq(j,controller_ns[i]);}jadd(j,",\"ipc\":");char actual[6][32];for(unsigned i=0;i<6;i++){nsread("/proc/self",nsnames[i],actual[i]);NEED((i>=4)==!strcmp(actual[i],controller_ns[i]),"actual namespace separation/time sharing");}jq(j,actual[3]);jadd(j,",\"mnt\":");jq(j,actual[0]);jadd(j,",\"mountinfo_sha256\":");jq(j,mhash);jadd(j,",\"net\":");jq(j,actual[1]);jadd(j,",\"pid\":");jq(j,actual[2]);jadd(j,",\"time\":");jq(j,actual[5]);jadd(j,",\"user\":");jq(j,actual[4]);jadd(j,"}");
 jadd(j,",\"quota\":{\"file_max_bytes\":16777216,\"hardlinks\":\"DENY_KERNEL_POLICY\",\"kind\":\"shared-tmpfs-v1\",\"max_bytes\":67108864,\"max_inodes\":133,\"max_regular_entries\":128,\"pool_mount_id\":%lu}",cover(cfg[DX_POOL])->id);
 struct statvfs actualpool;NEED(!statvfs(cfg[DX_POOL],&actualpool),"measured pool statvfs");jadd(j,",\"runtime\":{\"cgroup\":{\"memory_max_bytes\":2147483648,\"memory_swap_max_bytes\":0,\"pids_max\":1},\"mountinfo_base64\":");jb64(j,mountinfo);jadd(j,",\"policy_sha256\":");jq(j,cfg[DX_POLICY_SHA]);jadd(j,",\"pool_capacity_bytes\":%llu,\"pool_files\":%llu,\"python_sha256\":",(unsigned long long)actualpool.f_blocks*actualpool.f_frsize,(unsigned long long)actualpool.f_files);jq(j,cfg[DX_PYTHON_SHA]);jadd(j,",\"reservation_bytes\":%llu,\"reservation_entries\":4,\"rlimits\":{",(unsigned long long)reserve_bytes);
 const char*rn[]={"AS","CORE","CPU","FSIZE","NOFILE"};const int ri[]={RLIMIT_AS,RLIMIT_CORE,RLIMIT_CPU,RLIMIT_FSIZE,RLIMIT_NOFILE};const rlim_t rv[]={DX_MEMORY_MAX,0,150,DX_FILE_MAX,96};for(unsigned i=0;i<5;i++){struct rlimit r;NEED(!getrlimit(ri[i],&r)&&r.rlim_cur==rv[i]&&r.rlim_max==rv[i],"measured real rlimit");jadd(j,"%s\"%s\":[%llu,%llu]",i?",":"",rn[i],(unsigned long long)r.rlim_cur,(unsigned long long)r.rlim_max);}jadd(j,"},\"rootfs_digest\":");jq(j,cfg[DX_ROOTFS_DIGEST]);jadd(j,",\"status_base64\":");jb64(j,status);jadd(j,"}}");
 free(status);free(mountinfo);free(mount_rows);mount_rows=NULL;mount_count=0;
}

static const char*envkeys[]={"DX_ADMISSION_RECEIPT","DX_ADMISSION_RECEIPT_SHA256","DX_EMPTY_CWD","DX_EVIDENCE_DIR","DX_EXECUTION_MODE","DX_EXPECTED_GID","DX_EXPECTED_UID","DX_KERNEL_POLICY_SHA256","DX_PREPARED_CACHE","DX_PREPARED_CACHE_SHA256","DX_RUNNER_SHA256","DX_SCRATCH_DIR","DX_SOURCE_BRANCH","DX_SOURCE_HEAD","DX_UPLOAD_DIR","DX_WORKLOAD_NONCE","HOME","LANG","LC_ALL","PATH","PYTEST_DISABLE_PLUGIN_AUTOLOAD","PYTHONDONTWRITEBYTECODE","ROOT_APPROVED_PARTNER_DX","RUN_PARTNER_DX_METADATA"};
static char envvalues[24][4096],*envp[25];
static void seal_parse(Reader*r,char**admission,size_t*alen,char hash[65]){
 *alen=ru32(r);
 NEED(*alen>1&&*alen<=DX_RECEIPT_MAX&&*alen<=r->n-r->p,"admission size");
 *admission=(char*)r->b+r->p;r->p+=*alen;
 NEED((*admission)[*alen-1]=='\n'&&(*admission)[0]=='{'&&(*admission)[*alen-2]=='}',"admission framing");
 for(size_t i=0;i<*alen;i++)NEED((unsigned char)(*admission)[i]<128&&(*admission)[i],"admission ASCII bytes");
 hashbytes(*admission,*alen,hash);
 NEED(ru32(r)==24,"exact env count");
 for(unsigned i=0;i<24;i++){
  char k[128];rstr(r,k,sizeof(k));
  NEED(!strcmp(k,envkeys[i]),"exact sorted environment keys");
  rstr(r,envvalues[i],sizeof(envvalues[i]));
  size_t n=strlen(k)+strlen(envvalues[i])+2;
  envp[i]=malloc(n);NEED(envp[i],"env allocation");
  snprintf(envp[i],n,"%s=%s",k,envvalues[i]);
 }
 NEED(r->p==r->n,"SEAL trailing bytes");envp[24]=NULL;
 NEED(!strcmp(envvalues[0],"/inputs/admission/admission.json")&&!strcmp(envvalues[1],hash)&&!strcmp(envvalues[4],"kernel-controlled-v1")&&!strcmp(envvalues[5],cfg[DX_GID])&&!strcmp(envvalues[6],cfg[DX_UID])&&!strcmp(envvalues[7],cfg[DX_POLICY_SHA])&&!strcmp(envvalues[8],cfg[DX_CACHE_GUEST])&&hexstr(envvalues[9],64)&&!strcmp(envvalues[10],cfg[DX_RUNNER_SHA])&&!strcmp(envvalues[12],cfg[DX_SOURCE_BRANCH])&&!strcmp(envvalues[13],cfg[DX_SOURCE_HEAD])&&hexstr(envvalues[15],64)&&!strcmp(envvalues[16],cfg[DX_HOME]),"sealed environment bindings");
 const unsigned wi[]={2,14,3,11};const char*names[]={"cwd","upload","evidence","scratch"};
 for(unsigned i=0;i<4;i++){
  char p[4096];NEED(snprintf(p,sizeof(p),"%s/%s",cfg[DX_POOL],names[i])<(int)sizeof(p),"work environment length");
  NEED(!strcmp(p,envvalues[wi[i]]),"fixed work environment");
 }
 NEED(!strcmp(envvalues[17],"C.UTF-8")&&!strcmp(envvalues[18],"C.UTF-8")&&!strcmp(envvalues[19],"/usr/bin:/bin"),"fixed locale/path");
 for(unsigned i=20;i<24;i++)NEED(!strcmp(envvalues[i],"1"),"fixed gate environment");
}

static void child_run(int boot,int out,int err,int nullfd,int pythonfd,int parentfd){
 child_channel=boot;
 NEED(!prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0),"bootstrap parent death");
 NEED(dup2(nullfd,0)==0&&dup2(out,1)==1&&dup2(err,2)==2,"candidate stdio");
 NEED(dup3(pythonfd,DX_EXEC_FD,O_CLOEXEC)==DX_EXEC_FD,"reserved ELF fd96");
 NEED(dup3(boot,DX_BOOT_FD,O_CLOEXEC)==DX_BOOT_FD,"reserved bootstrap fd97");
 NEED(dup3(parentfd,98,O_CLOEXEC)==98,"pinned outside parent liveness fd98");
 child_channel=DX_BOOT_FD;
 NEED(!syscall(SYS_close_range,3,95,0)&&!syscall(SYS_close_range,99,~0U,0),"close inherited host capabilities");
 struct sigaction d={0};d.sa_handler=SIG_DFL;sigemptyset(&d.sa_mask);for(int s=1;s<NSIG;s++){if(s==SIGKILL||s==SIGSTOP||s==32||s==33)continue;NEED(!sigaction(s,&d,NULL),"bootstrap default signal handlers");}sigset_t empty;sigemptyset(&empty);NEED(!sigprocmask(SIG_SETMASK,&empty,NULL),"bootstrap empty signal mask");
 mount_setup();limits_and_identity();
 NEED(!prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0),"restore parent death after UID drop");
 struct pollfd parent_live={98,POLLIN,0};
 NEED(poll(&parent_live,1,0)==0,"broker died across identity transition");
 NEED(!close(98),"close parent liveness capability before filter");
 char h[65];hashfd(DX_EXEC_FD,h,DX_RUNTIME_ELF_MAX);NEED(!strcmp(h,cfg[DX_PYTHON_SHA]),"bootstrap exact ELF bytes");int l=filter_install();listener_send(l);
 char request='M';bootwrite(DX_BOOT_FD,&request,1);uint64_t physical[2];bootread(DX_BOOT_FD,physical,sizeof(physical));Json*j=calloc(1,sizeof(Json));NEED(j,"measurement JSON allocation");bootstrap_ready(j,physical[0],physical[1]);uint32_t n=(uint32_t)j->n;bootwrite(DX_BOOT_FD,&n,sizeof(n));bootwrite(DX_BOOT_FD,j->b,j->n);free(j);
 unsigned char length[4];bootread(DX_BOOT_FD,length,4);n=le32(length);NEED(n<=DX_FRAME_MAX&&n>0,"bootstrap SEAL bound");Reader r={malloc(n+1),n,0};NEED(r.b,"bootstrap SEAL allocation");bootread(DX_BOOT_FD,r.b,n);r.b[n]=0;char*a;size_t alen;seal_parse(&r,&a,&alen,h);hashfile("/inputs/admission/admission.json",h,DX_RECEIPT_MAX);
 /* Measurement is repeated after seal; it must stay byte-for-byte identical.
  * File content writes through the outside writer do not alter mountinfo. */
 char*status=readfixed("/proc/self/status",DX_PROC_MAX);status_exact(status,"NoNewPrivs","1");status_exact(status,"Seccomp","2");free(status);
 char*final_mountinfo=readfixed("/proc/self/mountinfo",DX_PROC_MAX);char final_mount_hash[65];
 hashbytes(final_mountinfo,strlen(final_mountinfo),final_mount_hash);free(final_mountinfo);
 NEED(!strcmp(final_mount_hash,ready_mount_hash),"no mount transitions between measurement and exec");
 NEED(!chdir(envvalues[2]),"candidate empty cwd");free(r.b);
 char runner[4096],pythonargv[4096];NEED(snprintf(runner,sizeof(runner),"%s/clearledger/server/tests/partner_dx_metadata_approved.py",cfg[DX_SOURCE])<(int)sizeof(runner),"runner path");NEED(snprintf(pythonargv,sizeof(pythonargv),"%s/bin/python",cfg[DX_VENV])<(int)sizeof(pythonargv),"python argv0");hashfile(runner,cfg[DX_RUNNER_SHA],DX_FILE_MAX);
 char armed='E';bootwrite(DX_BOOT_FD,&armed,1);char go;bootread(DX_BOOT_FD,&go,1);NEED(go=='G',"outside watchdog exec arm");
 char*args[]={pythonargv,"-I","-S","-B",runner,"--execute-approved-partner-dx-kernel-v1",NULL};
 (void)syscall(SYS_execveat,DX_EXEC_FD,"",args,envp,AT_EMPTY_PATH);
 /* No retry, fallback or second exec. A failed initial exec is a rejected run. */
 fatal("initial execveat failed");
}

typedef struct {uint64_t ms,free;unsigned phase;} Sample;
static Sample trace[512];
static unsigned trace_count=0;
static atomic_int phase=0;
static atomic_int exec_confirmed=0;
static atomic_ullong last_sample=0;
static uint64_t first_notification=0;
static unsigned continue_count=0;
static bool exec_observed=false;
static uint64_t setup_deadline=0;
static timer_t safety_timer;
static char cgroup_name[128];
static int cgroup_parent_fd=-1;

/* This periodic kernel timer has no dependency on the Python event loop,
 * notification ioctl, statvfs, pthread mutex or output pipe. Its handler only
 * reads lock-free atomics/monotonic time and asks the kernel to kill the pidfd.
 * The monitoring thread does actual fstatvfs at one-second intervals. */
_Static_assert(ATOMIC_LLONG_LOCK_FREE==2,"64-bit atomics must be lock free");
static void safety_tick(int sig){
 (void)sig;
 uint64_t t=nowms(),d=atomic_load(&wall_deadline),last=atomic_load(&last_sample);
 if(atomic_load(&rejected)||(d&&t>=d)||(!d&&t>=setup_deadline)||(last&&t-last>DX_GAP_MS)){
  killreject();_exit(120);
 }
}
static void timer_arm(void){
 struct sigaction a={0};a.sa_handler=safety_tick;sigemptyset(&a.sa_mask);
 NEED(!sigaction(SIGRTMIN,&a,NULL),"native safety signal");
 struct sigevent e={0};e.sigev_notify=SIGEV_SIGNAL;e.sigev_signo=SIGRTMIN;
 NEED(!timer_create(CLOCK_MONOTONIC,&e,&safety_timer),"native monotonic safety timer");
 struct itimerspec t={{0,100000000},{0,100000000}};
 NEED(!timer_settime(safety_timer,0,&t,NULL),"arm native safety timer");
}
static void physical_sample(unsigned which){
 struct statvfs v;
 pthread_mutex_lock(&sample_lock);
 if(which==4)which=(unsigned)atomic_load(&phase);
 /* Phase 3 is the short permission-to-observation interval. No unproved
  * "during" sample is manufactured from a still-blocked native bootstrap. */
 if(which==3){pthread_mutex_unlock(&sample_lock);killreject();return;}
 if(which==1){
  struct pollfd live={pidfd,POLLIN,0};
  if(!atomic_load(&exec_confirmed)){pthread_mutex_unlock(&sample_lock);killreject();return;}
  int q=poll(&live,1,0);
  if(q<0){pthread_mutex_unlock(&sample_lock);killreject();return;}
  if(q>0){which=2;atomic_store(&phase,2);}
 }
 uint64_t start=nowms();
 if(fstatvfs(storagefd,&v)||!v.f_frsize||v.f_bavail>UINT64_MAX/v.f_frsize){pthread_mutex_unlock(&sample_lock);killreject();return;}
 if(which==1){
  struct pollfd live={pidfd,POLLIN,0};int q=poll(&live,1,0);
  if(q<0){pthread_mutex_unlock(&sample_lock);killreject();return;}
  if(q>0){
   /* Exit overlapped this observation. Repeat only as a real AFTER sample;
    * do not count the ambiguous first observation as live execution. */
   which=2;atomic_store(&phase,2);
   if(fstatvfs(storagefd,&v)||!v.f_frsize||v.f_bavail>UINT64_MAX/v.f_frsize){pthread_mutex_unlock(&sample_lock);killreject();return;}
  }
 }
 uint64_t end=nowms(),free=(uint64_t)v.f_bavail*v.f_frsize;
 uint64_t gap=sample_ms?end-sample_ms:0;
 if(end-start>DX_GAP_MS||gap>DX_GAP_MS||free<DX_FLOOR_BYTES||trace_count>=512){
  pthread_mutex_unlock(&sample_lock);killreject();return;
 }
 if(gap>maxgap)maxgap=gap;
 sample_ms=end;atomic_store(&last_sample,end);
 if(!trace_count)before_free=free;
 if(which==1){if(!samples||free<minimum_free)minimum_free=free;samples++;}
 if(which==2)after_free=free;
 trace[trace_count++]=(Sample){end,free,which};
 pthread_mutex_unlock(&sample_lock);
}
static void*watchdog(void*unused){
 (void)unused;
 int timer=timerfd_create(CLOCK_MONOTONIC,TFD_CLOEXEC);
 if(timer<0){killreject();return NULL;}
 struct itimerspec it={{1,0},{1,0}};
 if(timerfd_settime(timer,0,&it,NULL)){close(timer);killreject();return NULL;}
 while(!atomic_load(&watch_stop)&&!atomic_load(&rejected)){
  struct pollfd p={timer,POLLIN,0};
  int q=poll(&p,1,100);
  if(q<0&&errno==EINTR)continue;
  if(q<0){killreject();break;}
  if(q&&p.revents&POLLIN){
   uint64_t ticks=0;
   if(read(timer,&ticks,sizeof(ticks))!=sizeof(ticks)||ticks!=1){killreject();break;}
   physical_sample(4);
  }
 }
 close(timer);return NULL;
}
static void cgroup_value(const char*name,const char*value){
 int fd=openat(cgroupfd,name,O_WRONLY|O_CLOEXEC|O_NOFOLLOW);
 NEED(fd>=0,"cgroup controller unavailable");
 NEED(write(fd,value,strlen(value))==(ssize_t)strlen(value),"cgroup hard cap write");
 NEED(!close(fd),"cgroup write close");
 fd=openat(cgroupfd,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
 NEED(fd>=0,"cgroup readback open");char b[128]={0};
 ssize_t n=read(fd,b,sizeof(b)-1);NEED(n>0&&n<(ssize_t)sizeof(b)-1,"cgroup readback");
 if(b[n-1]=='\n')b[n-1]=0;
 NEED(!strcmp(b,value),"cgroup hard cap not applied");NEED(!close(fd),"cgroup read close");
}
static void cgroup_setup(void){
 cgroup_parent_fd=open(cfg[DX_CGROUP_PARENT],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
 NEED(cgroup_parent_fd>=0,"cgroup parent open");
 struct statfs fs;NEED(!fstatfs(cgroup_parent_fd,&fs)&&fs.f_type==0x63677270,"actual cgroup v2");
 snprintf(cgroup_name,sizeof(cgroup_name),"dx-%lu-%llu",(unsigned long)getpid(),(unsigned long long)nowms());
 NEED(!mkdirat(cgroup_parent_fd,cgroup_name,0700),"unique empty candidate cgroup");
 cgroupfd=openat(cgroup_parent_fd,cgroup_name,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
 NEED(cgroupfd>=0,"candidate cgroup open");
 cgroup_value("pids.max","1");cgroup_value("memory.max","2147483648");
 cgroup_value("memory.swap.max","0");cgroup_value("memory.oom.group","1");
}
static uint64_t cgroup_number(const char*file){
 int fd=openat(cgroupfd,file,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);NEED(fd>=0,"cgroup number open");
 char b[128]={0};ssize_t n=read(fd,b,sizeof(b)-1);NEED(n>0&&n<(ssize_t)sizeof(b)-1,"cgroup number read");
 close(fd);if(b[n-1]=='\n')b[n-1]=0;return decimal(b);
}
static void cgroup_verify_live(void){
 NEED(cgroup_number("pids.current")==1&&cgroup_number("pids.max")==1,"one candidate kernel task");
 NEED(cgroup_number("memory.max")==DX_MEMORY_MAX&&cgroup_number("memory.swap.max")==0,"current cgroup hard memory caps");
 char p[128];snprintf(p,sizeof(p),"/proc/%ld/task",(long)childpid);
 DIR*d=opendir(p);NEED(d,"actual candidate task census");unsigned count=0;struct dirent*e;
 while((e=readdir(d)))if(strcmp(e->d_name,".")&&strcmp(e->d_name,".."))count++;
 closedir(d);NEED(count==1,"trusted bootstrap single thread");
}
static void record_meta(unsigned op,const void*p,size_t n){
 (void)op;(void)p;
 NEED(metadata_bytes+n+16<=reserve_sizes[1],"native metadata reserve exhausted");
 metadata_bytes+=n+16;
}
static void pool_open_reserve(void){
 char p[8192];NEED(snprintf(p,sizeof(p),"/proc/%ld/root%s",(long)childpid,cfg[DX_POOL])<(int)sizeof(p),"pool proc path");
 poolfd=open(p,O_RDONLY|O_DIRECTORY|O_CLOEXEC);NEED(poolfd>=0,"outside retained shared pool");
 struct statvfs v;NEED(!fstatvfs(poolfd,&v)&&v.f_blocks>0&&v.f_frsize>0&&v.f_blocks<=DX_POOL_BYTES/v.f_frsize&&v.f_files>0&&v.f_files<=133,"outside actual shared quota");
 for(unsigned i=0;i<4;i++){
  reserves[i]=openat(poolfd,".",O_TMPFILE|O_RDWR|O_CLOEXEC,0600);
  NEED(reserves[i]>=0,"unnamed shared-pool reservation");
  NEED(!posix_fallocate(reserves[i],0,(off_t)reserve_sizes[i]),"physical shared-pool fallocate reservation");
  struct stat s;NEED(!fstat(reserves[i],&s)&&S_ISREG(s.st_mode)&&s.st_nlink==0&&s.st_uid==0,"outside-only unnamed file");
 }
}
static void inspect_initial(struct seccomp_notif*n){
 NEED(n->flags==0&&n->pid==(uint32_t)childpid&&n->data.arch==AUDIT_ARCH_X86_64,"initial notification identity");
 NEED(n->data.nr==__NR_execveat&&n->data.args[0]==DX_EXEC_FD&&n->data.args[4]==AT_EMPTY_PATH,"initial exact execveat");
 NEED(n->data.args[1]>0&&n->data.args[2]>0&&n->data.args[3]>0,"bootstrap argv/path pointers");
 cgroup_verify_live();
 char byte=1;struct iovec local={&byte,1},remote={(void*)(uintptr_t)n->data.args[1],1};
 NEED(process_vm_readv(childpid,&local,1,&remote,1,0)==1&&byte==0,"trusted initial empty pathname");
 char path[128];snprintf(path,sizeof(path),"/proc/%ld/fd/96",(long)childpid);
 int fd=open(path,O_RDONLY|O_CLOEXEC);NEED(fd>=0,"inspect pinned initial ELF");
 struct stat s;NEED(!fstat(fd,&s)&&s.st_dev==python_stat.st_dev&&s.st_ino==python_stat.st_ino&&S_ISREG(s.st_mode),"initial ELF identity");
 char hash[65];hashfd(fd,hash,DX_RUNTIME_ELF_MAX);NEED(!strcmp(hash,cfg[DX_PYTHON_SHA]),"initial ELF bytes");close(fd);
 snprintf(path,sizeof(path),"/proc/%ld/status",(long)childpid);char*status=readfixed(path,DX_PROC_MAX);
 char ids[128];snprintf(ids,sizeof(ids),"%u\t%u\t%u\t%u",uid,uid,uid,uid);status_exact(status,"Uid",ids);
 snprintf(ids,sizeof(ids),"%u\t%u\t%u\t%u",gid,gid,gid,gid);status_exact(status,"Gid",ids);
 status_exact(status,"Groups","");status_exact(status,"NoNewPrivs","1");status_exact(status,"Seccomp","2");
 const char*caps[]={"CapInh","CapPrm","CapEff","CapBnd","CapAmb"};
 for(unsigned i=0;i<5;i++)status_exact(status,caps[i],"0000000000000000");free(status);
}
static void notification_once(int listener){
 struct seccomp_notif_sizes sizes;
 NEED(!syscall(SYS_seccomp,SECCOMP_GET_NOTIF_SIZES,0,&sizes),"native notification ABI sizes");
 NEED(sizes.seccomp_notif>=sizeof(struct seccomp_notif)&&sizes.seccomp_notif<=4096&&sizes.seccomp_notif_resp>=sizeof(struct seccomp_notif_resp)&&sizes.seccomp_notif_resp<=4096,"bounded notification ABI");
 struct seccomp_notif*n=calloc(1,sizes.seccomp_notif);struct seccomp_notif_resp*r=calloc(1,sizes.seccomp_notif_resp);
 NEED(n&&r,"notification allocation");
 for(;;){
  if(ioctl(listener,SECCOMP_IOCTL_NOTIF_RECV,n)==0)break;
  if(errno==EINTR&&!atomic_load(&rejected))continue;
  fatal("initial notification receive failure");
 }
 NEED(!ioctl(listener,SECCOMP_IOCTL_NOTIF_ID_VALID,&n->id),"initial notification ID live");
 inspect_initial(n);
 NEED(!ioctl(listener,SECCOMP_IOCTL_NOTIF_ID_VALID,&n->id),"initial notification still live");
 NEED(continue_count==0,"one shot permission not reusable");
 first_notification=n->id;
 /* Consume BEFORE CONTINUE. No retry of SEND, no candidate-path authorization.
  * Only this trusted single-thread bootstrap has run; pointer inspection above
  * is never applied to untrusted code to grant a later syscall continuation. */
 continue_count=1;
 physical_sample(0);
 NEED(!atomic_load(&rejected),"initial physical floor");
 atomic_store(&wall_deadline,nowms()+DX_WALL_MS);
 atomic_store(&phase,3);
 r->id=n->id;r->flags=SECCOMP_USER_NOTIF_FLAG_CONTINUE;
 NEED(!ioctl(listener,SECCOMP_IOCTL_NOTIF_SEND,r),"single CONTINUE failed; no retry");
 free(n);free(r);
}
static void observe_exec(void){
 char p[128];snprintf(p,sizeof(p),"/proc/%ld/exe",(long)childpid);
 int fd=open(p,O_RDONLY|O_CLOEXEC);NEED(fd>=0,"kernel exec identity evidence unavailable");
 struct stat s;NEED(!fstat(fd,&s)&&s.st_dev==python_stat.st_dev&&s.st_ino==python_stat.st_ino,"kernel committed pinned ELF");
 close(fd);exec_observed=true;
 atomic_store(&exec_confirmed,1);atomic_store(&phase,1);
 physical_sample(1);
 NEED(!atomic_load(&rejected),"real committed-exec physical sample");
 Json*j=calloc(1,sizeof(Json));NEED(j,"exec event allocation");
 jadd(j,"{\"consumed\":true,\"continue_count\":1,\"exec_observed\":true,\"notification_id\":%llu,\"pid\":%ld}",(unsigned long long)first_notification,(long)childpid);
 jsonframe(DX_EXEC,j);free(j);
}
static void output_read(int fd,unsigned op){
 unsigned char b[DX_OUTPUT_CHUNK];ssize_t n=read(fd,b,sizeof(b));
 if(n<0&&(errno==EINTR||errno==EAGAIN))return;
 NEED(n>=0,"candidate output read");if(!n)return;
 NEED(output_bytes+(uint64_t)n<=DX_OUTPUT_MAX,"combined stdout/stderr cap");
 NEED(pwrite(reserves[0],b,(size_t)n,(off_t)output_bytes)==n,"shared-pool output accounting write");
 output_bytes+=(uint64_t)n;frame(op,b,(size_t)n);
}
static void native_trace(Json*j){
 char outputhash[65];NEED(!ftruncate(reserves[0],(off_t)output_bytes),"actual output file length");
 hashfd(reserves[0],outputhash,DX_OUTPUT_MAX);
 jadd(j,"{\"clock\":\"CLOCK_MONOTONIC_MS\",\"failures\":[],\"firstnotify\":{\"consumed\":true,\"continue_count\":%u,\"exec_observed\":%s,\"id\":%llu,\"pid\":%ld},\"format\":\"elsy.partner-dx.native-trace.v1\",\"output_bytes\":%llu,\"output_sha256\":",continue_count,exec_observed?"true":"false",(unsigned long long)first_notification,(long)childpid,(unsigned long long)output_bytes);jq(j,outputhash);jadd(j,",\"samples\":[");
 pthread_mutex_lock(&sample_lock);
 for(unsigned i=0;i<trace_count;i++){
  Sample*s=&trace[i];const char*names[]={"BEFORE","DURING","AFTER"};
  jadd(j,"%s{\"free_bytes\":%llu,\"measured_ms\":%llu,\"phase\":\"%s\"}",i?",":"",(unsigned long long)s->free,(unsigned long long)s->ms,names[s->phase]);
 }
 pthread_mutex_unlock(&sample_lock);
 jadd(j,"],\"storage_id\":");jq(j,cfg[DX_STORAGE_ID]);jadd(j,"}\n");
 NEED(j->n<=reserve_sizes[1]&&metadata_bytes+j->n<=reserve_sizes[1],"metadata/trace physical reservation budget");
 NEED(pwrite(reserves[1],j->b,j->n,0)==(ssize_t)j->n,"persist actual native trace");
 NEED(!ftruncate(reserves[1],(off_t)j->n)&&!fsync(reserves[1])&&!fsync(reserves[0]),"persist bounded native logs");
}
static unsigned copied_entries=0;
static uint64_t copied_bytes=0;
static void copy_regular(int src,int target,const char*name,uid_t owner,gid_t group,mode_t mode){
 struct stat s;NEED(!fstat(src,&s)&&S_ISREG(s.st_mode)&&s.st_nlink<=1&&s.st_size>=0&&(uint64_t)s.st_size<=DX_FILE_MAX,"artifact regular bound");
 NEED(++copied_entries+2<=DX_POOL_ENTRIES&&copied_bytes+(uint64_t)s.st_size+2*DX_RECEIPT_MAX<=DX_POOL_BYTES,"artifact accounting with final+manifest");
 copied_bytes+=(uint64_t)s.st_size;
 int out=openat(target,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);NEED(out>=0,"exclusive artifact archive file");
 NEED(!lseek(src,0,SEEK_SET),"artifact rewind");unsigned char b[16384];uint64_t n=0;
 for(;;){ssize_t q=read(src,b,sizeof(b));if(q<0&&errno==EINTR)continue;NEED(q>=0,"artifact read");if(!q)break;NEED(write(out,b,(size_t)q)==q,"artifact copy write");n+=(uint64_t)q;}
 NEED(n==(uint64_t)s.st_size&&!fchown(out,owner,group)&&!fchmod(out,mode)&&!fsync(out),"artifact archive ownership/persistence");close(out);
}
static void copy_tree(int from,int to,unsigned depth){
 NEED(depth<=16,"artifact tree depth");int listing=dup(from);NEED(listing>=0,"artifact listing descriptor");DIR*d=fdopendir(listing);NEED(d,"artifact listing");struct dirent*e;
 while((e=readdir(d))){
  if(!strcmp(e->d_name,".")||!strcmp(e->d_name,".."))continue;
  NEED(e->d_name[0]&&strlen(e->d_name)<=255&&!strchr(e->d_name,'/'),"artifact entry name");
  struct stat s;NEED(!fstatat(from,e->d_name,&s,AT_SYMLINK_NOFOLLOW)&&s.st_uid==uid&&s.st_gid==gid&&!(s.st_mode&0077),"candidate artifact owner/private mode");
  if(S_ISDIR(s.st_mode)){
   NEED(++copied_entries+2<=DX_POOL_ENTRIES,"artifact directory entry budget");
   NEED(!mkdirat(to,e->d_name,0700),"artifact archive directory");
   int a=openat(from,e->d_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC),b=openat(to,e->d_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
   NEED(a>=0&&b>=0&&!fchown(b,uid,gid)&&!fchmod(b,0700),"artifact directory descriptors/owner");copy_tree(a,b,depth+1);close(a);NEED(!fsync(b),"artifact directory fsync");close(b);
  }else{
   NEED(S_ISREG(s.st_mode)&&s.st_nlink==1,"artifact symlink/special/hardlink forbidden");
   int a=openat(from,e->d_name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);NEED(a>=0,"artifact file open");copy_regular(a,to,e->d_name,uid,gid,0600);close(a);
  }
 }
 closedir(d);
}
static int archive_open(void){
 int archive=open(cfg[DX_HOST_EVIDENCE],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);NEED(archive>=0,"host archive open");
 struct stat s;NEED(!fstat(archive,&s)&&s.st_uid==0&&(s.st_mode&07777)==0700,"root private archive");return archive;
}
static void archive_copy(bool final){
 int archive=archive_open();
 if(!final){
  const char*dirs[]={"evidence","scratch"};
  for(unsigned i=0;i<2;i++){
   NEED(!mkdirat(archive,dirs[i],0700),"archive root exclusive directory");
   int from=openat(poolfd,dirs[i],O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC),to=openat(archive,dirs[i],O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
   NEED(from>=0&&to>=0&&!fchown(to,uid,gid),"archive root ownership");copy_tree(from,to,0);close(from);NEED(!fsync(to),"archive tree persistence");close(to);
  }
  int scratch=openat(poolfd,"scratch",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);NEED(scratch>=0,"retained scratch");
  NEED(!linkat(reserves[0],"",scratch,"controller-output.bin",AT_EMPTY_PATH),"materialize accounted native output");
  NEED(!linkat(reserves[1],"",scratch,"controller-native.json",AT_EMPTY_PATH),"materialize accounted native trace");close(scratch);
  int target=openat(archive,"scratch",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);NEED(target>=0,"archive native logs dir");
  copy_regular(reserves[0],target,"controller-output.bin",0,0,0600);copy_regular(reserves[1],target,"controller-native.json",0,0,0600);NEED(!fsync(target),"archive native logs persistence");close(target);
 }else{
  /* Only trusted native metadata changes during the post-hash FINALIZE phase.
   * Candidate is already waitpid-reaped and cannot race the exclusive copy. */
  int target=openat(archive,"scratch",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);NEED(target>=0,"final trace target");
  struct stat old;NEED(!fstatat(target,"controller-native.json",&old,AT_SYMLINK_NOFOLLOW)&&S_ISREG(old.st_mode)&&old.st_uid==0&&old.st_nlink==1,"old native trace identity");
  NEED(!unlinkat(target,"controller-native.json",0),"replace own provisional trace");
  copied_entries--;copied_bytes-=(uint64_t)old.st_size;
  copy_regular(reserves[1],target,"controller-native.json",0,0,0600);NEED(!fsync(target),"final trace archive fsync");close(target);
 }
 NEED(!fsync(archive),"host archive fsync");close(archive);
}
static void exit_event(unsigned op,int status){
 Json*j=calloc(1,sizeof(Json));NEED(j,"final event allocation");
 unsigned signal=WIFSIGNALED(status)?(unsigned)WTERMSIG(status):0;
 unsigned code=signal?128+signal:(unsigned)WEXITSTATUS(status);
 pthread_mutex_lock(&sample_lock);
 NEED(samples>0&&after_free>=DX_FLOOR_BYTES&&before_free>=DX_FLOOR_BYTES&&minimum_free>=DX_FLOOR_BYTES&&maxgap<=DX_GAP_MS,"complete real physical observations");
 jadd(j,"{\"artifacts_copied\":true,\"continue_count\":%u,\"exec_observed\":%s,\"exit_code\":%u,\"host_floor\":{\"after_free\":%llu,\"before_free\":%llu,\"max_gap_ms\":%llu,\"minimum_observed_during_free\":%llu,\"samples\":%llu,\"status\":\"PASS\",\"storage_id\":",continue_count,exec_observed?"true":"false",code,(unsigned long long)after_free,(unsigned long long)before_free,(unsigned long long)maxgap,(unsigned long long)minimum_free,(unsigned long long)samples);jq(j,cfg[DX_STORAGE_ID]);
 pthread_mutex_unlock(&sample_lock);
 jadd(j,"},\"output_bytes\":%llu,\"rejected\":%s,\"reservation_bytes\":%llu,\"reservation_entries\":4,\"termination_signal\":%u}",(unsigned long long)output_bytes,atomic_load(&rejected)||code!=0||!exec_observed?"true":"false",(unsigned long long)reserve_bytes,signal);
 jsonframe(op,j);free(j);
}

int main(int argc,char**argv){
 extern char**environ;
 NEED(argc==2&&!strcmp(argv[1],"--broker-v1"),"exact broker argv required");
 NEED(!*environ,"broker inherited environment must be empty");
 NEED(geteuid()==0&&getuid()==0&&getppid()>1,"privileged outside broker only");
 NEED(prctl(PR_GET_SECCOMP,0,0,0,0)==0,"unexpected inherited seccomp policy");
 pid_t original_parent=getppid();
 NEED(!prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0)&&getppid()==original_parent&&original_parent>1,"controller death race/liveness");
 struct __user_cap_header_struct caph={_LINUX_CAPABILITY_VERSION_3,0};
 struct __user_cap_data_struct capd[2]={{0},{0}};
 NEED(!syscall(SYS_capget,&caph,capd),"outside actual capabilities");
 const unsigned required_caps[]={CAP_SYS_ADMIN,CAP_SYS_PTRACE,CAP_SETUID,CAP_SETGID,CAP_SETPCAP,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH};
 for(unsigned i=0;i<sizeof(required_caps)/sizeof(*required_caps);i++){
  unsigned c=required_caps[i];
  NEED(capd[c/32].effective&(1U<<(c%32)),"outside required capability unavailable");
 }
 for(int fd=0;fd<=1;fd++){
  int flags=fcntl(fd,F_GETFL);
  NEED(flags>=0&&!fcntl(fd,F_SETFL,flags|O_NONBLOCK),"nonblocking outside protocol channels");
 }
 DIR*initial=opendir("/proc/self/fd");NEED(initial,"broker descriptor census");int self=dirfd(initial);struct dirent*entry;
 while((entry=readdir(initial))){if(entry->d_name[0]=='.')continue;unsigned long fd=strtoul(entry->d_name,NULL,10);NEED(fd<=2||(int)fd==self,"unexpected inherited broker capability");}closedir(initial);
 for(unsigned i=0;i<6;i++)nsread("/proc/self",nsnames[i],controller_ns[i]);
 Reader config=receive(DX_CONFIG);NEED(ru32(&config)==DX_CONFIG_FIELDS,"exact config count");
 for(unsigned i=0;i<DX_CONFIG_FIELDS;i++)rstr(&config,cfg[i],sizeof(cfg[i]));
 NEED(config.p==config.n,"CONFIG trailing bytes");free(config.b);
 const unsigned paths[]={DX_ROOTFS,DX_SOURCE,DX_NATIVE,DX_VENV,DX_CACHE_HOST,DX_CACHE_GUEST,DX_POLICY_HOST,DX_POOL,DX_HOME,DX_GIT_DIR,DX_GIT_COMMON,DX_STORAGE_PATH,DX_ADMISSION_HOST,DX_CGROUP_PARENT,DX_HOST_EVIDENCE};
 /* Guest-only destinations are checked in the prepared rootfs, not on host. */
 for(unsigned i=0;i<sizeof(paths)/sizeof(*paths);i++){
  unsigned k=paths[i];if(k==DX_CACHE_GUEST||k==DX_POOL||k==DX_HOME)continue;pathcheck(cfg[k]);
 }
 uint64_t u=decimal(cfg[DX_UID]),g=decimal(cfg[DX_GID]);NEED(u>0&&u<UINT32_MAX&&g>0&&g<UINT32_MAX,"nonzero uid/gid");uid=(uid_t)u;gid=(gid_t)g;
 const unsigned hashes[]={DX_PYTHON_SHA,DX_POLICY_SHA,DX_RUNNER_SHA,DX_CONTROLLER_SHA};
 for(unsigned i=0;i<4;i++)NEED(hexstr(cfg[hashes[i]],64),"independent hash grammar");
 NEED(!strncmp(cfg[DX_ROOTFS_DIGEST],"sha256:",7)&&hexstr(cfg[DX_ROOTFS_DIGEST]+7,64),"rootfs image digest grammar");
 NEED(hexstr(cfg[DX_SOURCE_HEAD],40)&&!strcmp(cfg[DX_POLICY_SHA],POLICY_SHA),"source/policy binding");
 NEED(strlen(cfg[DX_SOURCE_BRANCH])<=200&&strlen(cfg[DX_STORAGE_ID])<=128,"branch/storage bounds");
 NEED(!strcmp(strrchr(cfg[DX_POLICY_HOST],'/'),"/execute-policy.json")&&!strcmp(strrchr(cfg[DX_ADMISSION_HOST],'/'),"/admission.json"),"fixed sealed input basenames");
 input_mode(cfg[DX_POLICY_HOST],0400);input_mode(cfg[DX_ADMISSION_HOST],0400);input_mode(cfg[DX_CACHE_HOST],0600);
 singleton_parent(cfg[DX_POLICY_HOST]);singleton_parent(cfg[DX_ADMISSION_HOST]);singleton_parent(cfg[DX_CACHE_HOST]);
 hashfile(cfg[DX_POLICY_HOST],POLICY_SHA,DX_FILE_MAX);
 writer=open(cfg[DX_ADMISSION_HOST],O_WRONLY|O_CLOEXEC|O_NOFOLLOW);NEED(writer>=0,"preopen admission writer before RO bind");struct stat admission;NEED(!fstat(writer,&admission)&&admission.st_size==0,"fresh admission empty file");
 char python[4096];NEED(snprintf(python,sizeof(python),"%s/bin/python3.13",cfg[DX_NATIVE])<(int)sizeof(python),"pinned native ELF path");
 int pythonfd=open(python,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);NEED(pythonfd>=0,"pinned native ELF open");NEED(!fstat(pythonfd,&python_stat)&&S_ISREG(python_stat.st_mode),"actual native ELF regular");unsigned char elf[5];NEED(read(pythonfd,elf,5)==5&&!memcmp(elf,"\177ELF\2",5),"native ELF64 required");char hash[65];hashfd(pythonfd,hash,DX_RUNTIME_ELF_MAX);NEED(!strcmp(hash,cfg[DX_PYTHON_SHA]),"independent ELF SHA");
 storagefd=open(cfg[DX_STORAGE_PATH],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);NEED(storagefd>=0,"physical storage descriptor");struct statfs storagefs;NEED(!fstatfs(storagefd,&storagefs)&&(storagefs.f_type==0xef53||storagefs.f_type==0x58465342||storagefs.f_type==0x9123683e),"supported physical local filesystem required");
 struct stat storage;NEED(!fstat(storagefd,&storage),"physical storage stat");const unsigned physical[]={DX_ROOTFS,DX_SOURCE,DX_NATIVE,DX_VENV,DX_HOST_EVIDENCE};for(unsigned i=0;i<5;i++){struct stat s;NEED(!stat(cfg[physical[i]],&s)&&s.st_dev==storage.st_dev,"one configured physical storage must cover all snapshots/runtime/evidence");}
 physical_sample(0);NEED(!atomic_load(&rejected),"physical before floor");cgroup_setup();
 int boot[2],out[2],err[2];NEED(!socketpair(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0,boot)&&!pipe2(out,O_CLOEXEC)&&!pipe2(err,O_CLOEXEC),"trusted bootstrap/output channels");
 int nullfd=open("/dev/null",O_RDONLY|O_CLOEXEC);NEED(nullfd>=0,"candidate stdin null");
 int parentfd=(int)syscall(SYS_pidfd_open,getpid(),0);NEED(parentfd>=0,"pinned outside broker liveness pidfd");
 struct clone_args ca={0};ca.flags=CLONE_NEWPID|CLONE_NEWNS|CLONE_NEWNET|CLONE_NEWIPC|CLONE_INTO_CGROUP|CLONE_PIDFD;ca.pidfd=(uint64_t)(uintptr_t)&pidfd;ca.cgroup=(uint64_t)cgroupfd;ca.exit_signal=SIGCHLD;
 childpid=(pid_t)syscall(SYS_clone3,&ca,sizeof(ca));NEED(childpid>=0,"exact clone3 primitives unavailable; no fallback");
 if(childpid==0)child_run(boot[1],out[1],err[1],nullfd,pythonfd,parentfd);
 NEED(pidfd>=0,"atomic clone3 pidfd");close(parentfd);close(boot[1]);close(out[1]);close(err[1]);close(nullfd);close(pythonfd);
 /* Threads are created only outside and AFTER clone3: the candidate never
  * inherits a pthread runtime lock held by another parent thread. */
 setup_deadline=nowms()+30000;timer_arm();pthread_t monitor;
 NEED(!pthread_create(&monitor,NULL,watchdog,NULL),"independent native physical watchdog");
 int listener=listener_receive(boot[0]);char request;bootread(boot[0],&request,1);NEED(request=='M',"bootstrap measurement request");
 physical_sample(0);pthread_mutex_lock(&sample_lock);before_free=trace[trace_count-1].free;uint64_t before[2]={sample_ms,before_free};pthread_mutex_unlock(&sample_lock);bootwrite(boot[0],before,sizeof(before));
 uint32_t n;bootread(boot[0],&n,4);NEED(n>0&&n<DX_FRAME_MAX,"native measurement frame bound");Json*ready=calloc(1,sizeof(Json));NEED(ready,"READY allocation");bootread(boot[0],ready->b,n);ready->n=n;
 cgroup_verify_live();pool_open_reserve();
 /* READY was measured before reservations; unnamed inodes/bytes alter free
  * counts only. Total quota, mountinfo, role stat and identity stay identical. */
 jsonframe(DX_READY,ready);free(ready);
 Reader seal=receive(DX_SEAL);char*admissionbytes;size_t alen;seal_parse(&seal,&admissionbytes,&alen,hash);
 record_meta(DX_SEAL,seal.b,seal.n);
 NEED(write(writer,admissionbytes,alen)==(ssize_t)alen&&!fsync(writer),"seal actual admission bytes");NEED(!close(writer),"close admission writer");writer=-1;
 struct stat sealed;NEED(!lstat(cfg[DX_ADMISSION_HOST],&sealed)&&sealed.st_ino==admission.st_ino&&sealed.st_dev==admission.st_dev&&sealed.st_nlink==1&&(sealed.st_mode&07777)==0400,"sealed admission identity");
 unsigned char length[4];put32(length,(uint32_t)seal.n);bootwrite(boot[0],length,4);bootwrite(boot[0],seal.b,seal.n);free(seal.b);
 bootread(boot[0],&request,1);NEED(request=='E',"trusted initial exec armed");cgroup_verify_live();char go='G';bootwrite(boot[0],&go,1);
 notification_once(listener);
 for(int i=0;i<3;i++){int fd=i==0?boot[0]:i==1?out[0]:err[0];int flags=fcntl(fd,F_GETFL);NEED(flags>=0&&!fcntl(fd,F_SETFL,flags|O_NONBLOCK),"bounded native channel nonblocking");}
 int status=0;bool waited=false,stdout_done=false,stderr_done=false;
 while(!waited||!stdout_done||!stderr_done){
  NEED(!atomic_load(&rejected),"native independent control rejected");
  struct pollfd p[5]={{listener,POLLIN,0},{boot[0],POLLIN,0},{out[0],POLLIN,0},{err[0],POLLIN,0},{0,POLLIN,0}};
  int q=poll(p,5,100);if(q<0&&errno==EINTR)continue;NEED(q>=0,"native event loop poll");
  /* Every later exec, including absolute pathname or another fd, stays blocked
   * in USER_NOTIF until the outside broker kills it. Never receive/CONTINUE it. */
  NEED(!(p[0].revents&POLLIN),"subsequent exec notification denied");
  NEED(!(p[4].revents&(POLLIN|POLLHUP|POLLERR)),"unexpected controller message/EOF while running");
  if(!exec_observed&&(p[1].revents&(POLLIN|POLLHUP))){char b;ssize_t k=read(boot[0],&b,1);NEED(k==0,"bootstrap failed instead of committed exec");observe_exec();}
  if(p[2].revents&POLLIN)output_read(out[0],DX_STDOUT);
  if(p[3].revents&POLLIN)output_read(err[0],DX_STDERR);
  if(p[2].revents&POLLHUP){for(;;){struct pollfd f={out[0],POLLIN,0};if(poll(&f,1,0)<=0||!(f.revents&POLLIN))break;output_read(out[0],DX_STDOUT);}stdout_done=true;}
  if(p[3].revents&POLLHUP){for(;;){struct pollfd f={err[0],POLLIN,0};if(poll(&f,1,0)<=0||!(f.revents&POLLIN))break;output_read(err[0],DX_STDERR);}stderr_done=true;}
  if(!waited){pid_t w=waitpid(childpid,&status,WNOHANG);NEED(w>=0,"actual waitpid");if(w==childpid){waited=true;atomic_store(&phase,2);atomic_store(&wall_deadline,nowms()+30000);}}
 }
 NEED(exec_observed&&WIFEXITED(status)&&WEXITSTATUS(status)==0,"nonzero/signal/missing exec rejects run");
 NEED(cgroup_number("pids.current")==0,"candidate cgroup empty after wait");
 close(listener);close(boot[0]);close(out[0]);close(err[0]);physical_sample(2);
 Json*tracejson=calloc(1,sizeof(Json));NEED(tracejson,"trace allocation");native_trace(tracejson);archive_copy(false);physical_sample(2);exit_event(DX_EXIT,status);
 Reader finalize=receive(DX_FINALIZE);NEED(finalize.n==4&&ru32(&finalize)==0,"closed FINALIZE request");free(finalize.b);
 atomic_store(&watch_stop,1);
 struct timespec join_deadline;NEED(!clock_gettime(CLOCK_REALTIME,&join_deadline),"join deadline clock");join_deadline.tv_sec++;
 NEED(!pthread_timedjoin_np(monitor,NULL,&join_deadline),"bounded monitor join; timeout rejects");
 /* One frozen native sample set feeds BOTH persisted trace and FINAL. The
  * independent monotonic safety timer remains armed throughout persistence.
  * A separately samples physical floor around its external final publication. */
 physical_sample(2);
 tracejson->n=0;native_trace(tracejson);archive_copy(true);free(tracejson);
 exit_event(DX_FINAL,status);NEED(!timer_delete(safety_timer),"disarm completed native safety timer");
 for(unsigned i=0;i<4;i++)close(reserves[i]);close(poolfd);close(storagefd);close(pidfd);close(cgroupfd);
 NEED(!unlinkat(cgroup_parent_fd,cgroup_name,AT_REMOVEDIR),"remove own empty cgroup");close(cgroup_parent_fd);
 return 0;
}
