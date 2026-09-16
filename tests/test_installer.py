from pathlib import Path
import subprocess


ROOT=Path(__file__).parents[1]


def test_installer_preserves_ha_config_and_legacy_integration(tmp_path):
    config=tmp_path/'HA config'
    config.mkdir()
    (config/'configuration.yaml').write_text('default_config:\n')
    legacy=config/'custom_components/fitness'
    legacy.mkdir(parents=True)
    (legacy/'keep.txt').write_text('legacy')
    target=config/'custom_components/fitness_bridge'
    target.mkdir()
    (target/'old.txt').write_text('old bridge')
    result=subprocess.run(['bash',str(ROOT/'tools/install_bridge_a31.sh'),str(config)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert (legacy/'keep.txt').read_text()=='legacy'
    assert (config/'configuration.yaml').read_text()=='default_config:\n'
    assert len(list((config/'fitness_bridge_backups').glob('*/old.txt')))==1
    assert not (target/'old.txt').exists()
    for source in (ROOT/'custom_components/fitness_bridge').rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts and source.suffix in {'.py','.js','.json'}:
            assert (target/source.relative_to(ROOT/'custom_components/fitness_bridge')).read_bytes()==source.read_bytes()


def test_installer_rejects_non_ha_directory(tmp_path):
    result=subprocess.run(['bash',str(ROOT/'tools/install_bridge_a31.sh'),str(tmp_path)],capture_output=True,text=True)
    assert result.returncode!=0
    assert not (tmp_path/'custom_components').exists()
