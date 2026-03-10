import { type FC, memo } from 'react';
import { useTranslation } from 'react-i18next';

import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { SettingsItem } from '@/components/ui/settings-item';
import { StatusBar } from '@/components/ui/status-bar';
import type { Paths, PathValue, Settings } from '@/types';

interface MajsoulMaxSectionProps {
  settings: Settings;
  updateSetting: <P extends Paths<Settings>>(
    path: readonly [...P],
    value: PathValue<Settings, P>,
    shouldDebounce?: boolean,
  ) => void;
}

export const MajsoulMaxSection: FC<MajsoulMaxSectionProps> = memo(({ settings, updateSetting }) => {
  const { t } = useTranslation();

  return (
    <div className='space-y-4'>
      <h3 className='settings-section-title'>{t('settings.majsoulmax.title')}</h3>

      <StatusBar variant='info'>{t('settings.majsoulmax.mitm_only_notice')}</StatusBar>

      <SettingsItem
        label={t('settings.majsoulmax.mod_enable')}
        description={t('settings.majsoulmax.mod_enable_desc')}
        layout='row'
      >
        <Checkbox
          id='majsoulmax_mod_enable'
          checked={settings.majsoulmax.mod_enable}
          onCheckedChange={(checked) =>
            updateSetting(['majsoulmax', 'mod_enable'], checked === true)
          }
        />
      </SettingsItem>

      {settings.majsoulmax.mod_enable && (
        <div className='animate-in fade-in slide-in-from-top-2 ease-premium space-y-4 transition-all duration-500'>
          <SettingsItem
            label={t('settings.majsoulmax.liqi_auto_update')}
            description={t('settings.majsoulmax.liqi_auto_update_desc')}
            layout='row'
          >
            <Checkbox
              id='majsoulmax_liqi_auto_update'
              checked={settings.majsoulmax.liqi_auto_update}
              onCheckedChange={(checked) =>
                updateSetting(['majsoulmax', 'liqi_auto_update'], checked === true)
              }
            />
          </SettingsItem>

          <SettingsItem
            label={t('settings.majsoulmax.github_token')}
            description={t('settings.majsoulmax.github_token_desc')}
          >
            <Input
              type='password'
              value={settings.majsoulmax.github_token}
              placeholder='ghp_...'
              onChange={(e) => updateSetting(['majsoulmax', 'github_token'], e.target.value, true)}
            />
          </SettingsItem>

          {settings.majsoulmax.liqi_version && (
            <SettingsItem label={t('settings.majsoulmax.liqi_version')}>
              <span className='text-muted-foreground text-sm tabular-nums'>
                {settings.majsoulmax.liqi_version}
              </span>
            </SettingsItem>
          )}
        </div>
      )}
    </div>
  );
});

MajsoulMaxSection.displayName = 'MajsoulMaxSection';
