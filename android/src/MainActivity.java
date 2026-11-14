package io.github.haoye001.dragonpet;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private Button start;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (24 * getResources().getDisplayMetrics().density);
        content.setPadding(padding, padding * 3, padding, padding);
        TextView title = new TextView(this);
        title.setText("白龙娘桌宠");
        title.setTextSize(28);
        content.addView(title);
        TextView instructions = new TextView(this);
        instructions.setText("轻点播放动作，拖动调整位置，长按关闭。\n首次使用请允许显示在其他应用上层。");
        instructions.setPadding(0, padding, 0, padding);
        content.addView(instructions);
        start = button(content, "开启桌宠", view -> {
            if (!Settings.canDrawOverlays(this)) {
                startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName())));
                return;
            }
            startForegroundService(new Intent(this, PetService.class));
            moveTaskToBack(true);
        });
        button(content, "关闭桌宠", view -> stopService(new Intent(this, PetService.class)));
        setContentView(content);
    }

    @Override protected void onResume() {
        super.onResume();
        start.setText(Settings.canDrawOverlays(this) ? "开启桌宠" : "允许悬浮显示");
    }

    private Button button(LinearLayout parent, String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setOnClickListener(listener);
        parent.addView(button);
        return button;
    }
}
