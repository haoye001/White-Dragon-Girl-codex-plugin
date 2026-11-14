package io.github.haoye001.dragonpet;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.graphics.ImageDecoder;
import android.graphics.PixelFormat;
import android.graphics.drawable.Animatable2;
import android.graphics.drawable.AnimatedImageDrawable;
import android.graphics.drawable.Drawable;
import android.os.IBinder;
import android.provider.Settings;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.widget.ImageView;
import java.io.IOException;
import java.util.Random;

public final class PetService extends Service {
    private static final String STOP = "stop";
    private static final String IDLE = "idle.webp";
    private static final String[] ACTIONS = {"wave.webp", "heart.webp", "celebrate.webp", "sleepy.webp"};
    private final Random random = new Random();
    private WindowManager window;
    private WindowManager.LayoutParams layout;
    private ImageView pet;
    private AnimatedImageDrawable animation;
    private boolean attached;
    private boolean dragging;
    private float downX, downY;
    private int startX, startY;
    private final Runnable close = this::stopSelf;

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int id) {
        if (intent != null && STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel("pet", "白龙娘桌宠",
            NotificationManager.IMPORTANCE_LOW));
        PendingIntent stop = PendingIntent.getService(this, 0, new Intent(this, PetService.class).setAction(STOP),
            PendingIntent.FLAG_IMMUTABLE);
        startForeground(1, new Notification.Builder(this, "pet")
            .setSmallIcon(android.R.drawable.ic_menu_myplaces)
            .setContentTitle("白龙娘正在桌面陪伴")
            .setContentText("长按桌宠即可关闭")
            .addAction(new Notification.Action.Builder(null, "关闭桌宠", stop).build())
            .setOngoing(true).build());
        if (!Settings.canDrawOverlays(this)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (pet == null) {
            try {
                showPet();
            } catch (IOException | RuntimeException error) {
                android.util.Log.e("DragonPet", "Could not show pet", error);
                stopSelf();
            }
        }
        return START_NOT_STICKY;
    }

    private void showPet() throws IOException {
        window = getSystemService(WindowManager.class);
        int side = Math.round(144 * getResources().getDisplayMetrics().density);
        layout = new WindowManager.LayoutParams(side, side, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        layout.gravity = Gravity.TOP | Gravity.LEFT;
        layout.x = 0;
        layout.y = screenHeight() / 2;
        pet = new ImageView(this);
        pet.setContentDescription("白龙娘桌宠");
        pet.setOnClickListener(view -> playAction());
        pet.setOnTouchListener((view, event) -> handleTouch(event));
        play(IDLE, true);
        window.addView(pet, layout);
        attached = true;
    }

    private int screenHeight() { return getResources().getDisplayMetrics().heightPixels; }

    private boolean handleTouch(MotionEvent event) {
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                downX = event.getRawX();
                downY = event.getRawY();
                startX = layout.x;
                startY = layout.y;
                dragging = false;
                pet.postDelayed(close, ViewConfiguration.getLongPressTimeout());
                return true;
            case MotionEvent.ACTION_MOVE:
                int dx = Math.round(event.getRawX() - downX);
                int dy = Math.round(event.getRawY() - downY);
                int slop = ViewConfiguration.get(this).getScaledTouchSlop();
                if (!dragging && Math.hypot(dx, dy) > slop) {
                    dragging = true;
                    pet.removeCallbacks(close);
                }
                if (dragging) {
                    int width = getResources().getDisplayMetrics().widthPixels;
                    layout.x = Math.max(0, Math.min(width - layout.width, startX + dx));
                    layout.y = Math.max(0, Math.min(screenHeight() - layout.height, startY + dy));
                    window.updateViewLayout(pet, layout);
                }
                return true;
            case MotionEvent.ACTION_UP:
                pet.removeCallbacks(close);
                if (!dragging) pet.performClick();
                return true;
            case MotionEvent.ACTION_CANCEL:
                pet.removeCallbacks(close);
                return true;
            default:
                return false;
        }
    }

    private void playAction() {
        try {
            play(ACTIONS[random.nextInt(ACTIONS.length)], false);
        } catch (IOException error) {
            android.util.Log.e("DragonPet", "Could not play animation", error);
        }
    }

    private void play(String name, boolean loop) throws IOException {
        Drawable drawable = ImageDecoder.decodeDrawable(ImageDecoder.createSource(getAssets(), name));
        if (!(drawable instanceof AnimatedImageDrawable)) throw new IOException("Invalid animation: " + name);
        clearAnimation();
        animation = (AnimatedImageDrawable) drawable;
        animation.setRepeatCount(loop ? AnimatedImageDrawable.REPEAT_INFINITE : 0);
        if (!loop) {
            animation.registerAnimationCallback(new Animatable2.AnimationCallback() {
                @Override public void onAnimationEnd(Drawable finished) {
                    if (animation != finished) return;
                    try {
                        play(IDLE, true);
                    } catch (IOException error) {
                        stopSelf();
                    }
                }
            });
        }
        pet.setImageDrawable(animation);
        animation.start();
    }

    private void clearAnimation() {
        if (animation == null) return;
        animation.clearAnimationCallbacks();
        animation.stop();
        animation = null;
    }

    @Override public void onDestroy() {
        if (pet != null) pet.removeCallbacks(close);
        clearAnimation();
        if (attached) window.removeView(pet);
        super.onDestroy();
    }
}
