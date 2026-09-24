package com.timkay.driverecent;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.graphics.drawable.Icon;
import android.graphics.drawable.Drawable;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import java.util.Collections;
import android.net.Uri;
import android.widget.Toast;

public class MainActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (getIntent().getBooleanExtra("pin", false) || getIntent().getBooleanExtra("update", false)) {
            ShortcutManager manager = getSystemService(ShortcutManager.class);
            if (manager.isRequestPinShortcutSupported()) {
                Intent launch = new Intent(this, MainActivity.class).setAction(Intent.ACTION_VIEW);
                ShortcutInfo shortcut = new ShortcutInfo.Builder(this, "drive-recent")
                    .setShortLabel("Drive Recent")
                    .setIcon(driveIcon())
                    .setIntent(launch).build();
                manager.updateShortcuts(Collections.singletonList(shortcut));
                if (!getIntent().getBooleanExtra("update", false)) manager.requestPinShortcut(shortcut, null);
            } else {
                Toast.makeText(this, "Drag Drive Recent from your app drawer to Home", Toast.LENGTH_LONG).show();
            }
        } else {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://drive.google.com/drive/recent"))
                    .setPackage("com.google.android.apps.docs"));
            } catch (android.content.ActivityNotFoundException e) {
                Toast.makeText(this, "Google Drive is not installed", Toast.LENGTH_LONG).show();
            }
        }
        finish();
    }
    private Icon driveIcon() {
        try {
            Drawable drawable = getPackageManager().getApplicationIcon("com.google.android.apps.docs");
            Bitmap bitmap = Bitmap.createBitmap(192, 192, Bitmap.Config.ARGB_8888);
            drawable.setBounds(0, 0, 192, 192);
            drawable.draw(new Canvas(bitmap));
            return Icon.createWithBitmap(bitmap);
        } catch (android.content.pm.PackageManager.NameNotFoundException e) {
            return Icon.createWithResource(this, android.R.drawable.ic_menu_recent_history);
        }
    }
}
