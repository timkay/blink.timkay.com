package com.timkay.blinkoverlay;
import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.util.Locale;

public class OverlayService extends Service {
 private final Handler handler = new Handler();
 private TextView text;
 private WindowManager wm;
 private String state="waiting", reading="Waiting for Blink";
 private long finish=0, changed=0, received=0;
 private final Runnable tick = new Runnable() { public void run() {
  long now=System.currentTimeMillis();
  long seconds=Math.max(0,(finish-now+999)/1000);
  long mins=(seconds+59)/60;
  String time=finish>0 ? String.format(Locale.US,"%d:%02d",mins/60,mins%60) : "—";
  String title=state.equals("stopped") ? "CHARGING STOPPED\nUnplug your car" : "Estimated remaining  " + time;
  String age=changed>0 ? " · since " + ((now-changed)/60000) + "m" : "";
  String extra=state.equals("unavailable") || now-received>20000 ? "\nWaiting for readable Blink status" : "";
  text.setText(title+"\n"+reading+age+extra);
  text.setTextColor(state.equals("stopped") ? 0xffffbb55 : Color.WHITE);
  handler.postDelayed(this,1000);
 }};
 public void onCreate() {
  super.onCreate();
  NotificationManager nm=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
  NotificationChannel channel=new NotificationChannel("overlay","Overlay service (silent)",NotificationManager.IMPORTANCE_LOW);
  channel.setSound(null,null); channel.enableVibration(false); nm.createNotificationChannel(channel);
  startForeground(1,new Notification.Builder(this,"overlay").setContentTitle("Blink overlay running").setSmallIcon(android.R.drawable.ic_dialog_info).build());
  wm=(WindowManager)getSystemService(WINDOW_SERVICE);
  text=new TextView(this); text.setTextSize(68); text.setPadding(18,12,18,12); text.setBackgroundColor(0xee17232e);
  WindowManager.LayoutParams lp=new WindowManager.LayoutParams(WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,android.graphics.PixelFormat.TRANSLUCENT);
  lp.gravity=Gravity.TOP|Gravity.CENTER_HORIZONTAL; lp.y=170; lp.alpha=0.8f;
  wm.addView(text,lp); handler.post(tick);
 }
 public int onStartCommand(Intent i,int flags,int id) {
  if(i!=null) {
   state=i.getStringExtra("state"); if(state==null)state="waiting";
   String r=i.getStringExtra("reading"); if(r!=null) reading=r;
   if(i.hasExtra("finish"))finish=i.getLongExtra("finish",0);
   if(i.hasExtra("changed"))changed=i.getLongExtra("changed",0);
   received=System.currentTimeMillis();
  }
  return START_NOT_STICKY;
 }
 public void onDestroy(){ handler.removeCallbacks(tick); if(text!=null)wm.removeView(text);super.onDestroy(); }
 public IBinder onBind(Intent i){return null;}
}
