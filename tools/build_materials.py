"""Generate project-owned cookable materials; contains no Bethesda content."""
import unreal as u
from pathlib import Path
import struct
import zlib
SOURCE=Path(__file__).resolve().parent
SHADERS=SOURCE.parent/'shaders'
L=u.MaterialEditingLibrary
T=u.AssetToolsHelpers.get_asset_tools()
D='/Game/UEMW/Materials'
u.EditorAssetLibrary.make_directory(D)
probe=u.MWBuildLibrary.create_ambient_probe()
if probe is None or not u.EditorAssetLibrary.save_loaded_asset(probe,False):raise RuntimeError('Ambient probe could not be created')
neutral_path=D+'/MW_NeutralDetail'
neutral=u.load_asset(neutral_path)
if neutral is None:
    # Project-owned neutral data, not replacement artwork or a Bethesda asset.
    def chunk(kind,payload):return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
    png=SOURCE.parent/'local/build-temp/MW_NeutralDetail.png'
    png.parent.mkdir(parents=True,exist_ok=True)
    png.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',4,4,8,6,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes([128,128,128,255])*4)*4))+chunk(b'IEND',b''))
    task=u.AssetImportTask();task.set_editor_property('filename',str(png));task.set_editor_property('destination_path',D);task.set_editor_property('destination_name','MW_NeutralDetail');task.set_editor_property('factory',u.TextureFactory());task.set_editor_property('automated',True);task.set_editor_property('save',True)
    T.import_asset_tasks([task]);neutral=u.load_asset(neutral_path)
if neutral is None:raise RuntimeError('Neutral packed surface texture missing')
neutral.set_editor_property('srgb',False)
neutral.set_editor_property('compression_settings',u.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
if not u.EditorAssetLibrary.save_loaded_asset(neutral,False):raise RuntimeError('Neutral surface texture could not be saved')
terrain_arrays={}
for label,srgb in (('Color',True),('Detail',False)):
    name='MW_Terrain'+label+'Fallback';array=u.load_asset(D+'/'+name)
    if array is None:array=u.MWBuildLibrary.create_terrain_fallback(name,srgb)
    if array is None:raise RuntimeError('Terrain array fallback could not be created')
    array.set_editor_property('srgb',srgb)
    array.set_editor_property('compression_settings',u.TextureCompressionSettings.TC_DEFAULT if srgb else u.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
    if not u.EditorAssetLibrary.save_loaded_asset(array,False):raise RuntimeError('Terrain array fallback could not be saved')
    terrain_arrays[label]=array
def expression(m,cls,**props):
    e=L.create_material_expression(m,cls)
    for k,v in props.items():e.set_editor_property(k,v)
    return e
def link(a,pin,b,target):
    if not L.connect_material_expressions(a,pin,b,target):raise RuntimeError('Material connection failed '+target)
def custom_node(m,filename,names,prefix=''):
    e=expression(m,u.MaterialExpressionCustom,output_type=u.CustomMaterialOutputType.CMOT_FLOAT3)
    inputs=[]
    for name in names:
        item=u.CustomInput();item.set_editor_property('input_name',name);inputs.append(item)
    e.set_editor_property('inputs',inputs)
    e.set_editor_property('code',prefix+(SHADERS/filename).read_text(encoding='utf-8'))
    return e
def output(e,pin,m,prop):
    if not L.connect_material_property(e,pin,prop):raise RuntimeError('Material output failed')

def clear_material(m):
    # UE 5.2 removes from the collection it is iterating and can leave half the
    # old expressions behind. Custom outputs must not accumulate on rebuild.
    for _ in range(16):
        count=L.get_num_material_expressions(m)
        if not count:return
        L.delete_all_material_expressions(m)
        if L.get_num_material_expressions(m)>=count:raise RuntimeError('Material expression cleanup did not progress')
    raise RuntimeError('Material expression cleanup exceeded its bounded passes')
foliage_model=next((getattr(u.MaterialShadingModel,n)for n in dir(u.MaterialShadingModel)if n.startswith('MSM_')and 'FOLIAGE'in n),None)
if foliage_model is None:raise RuntimeError('Installed engine has no two-sided foliage shading model')
policies=[('Opaque',u.BlendMode.BLEND_OPAQUE),('Masked',u.BlendMode.BLEND_MASKED),('Foliage',u.BlendMode.BLEND_MASKED),('Translucent',u.BlendMode.BLEND_TRANSLUCENT),
          ('Additive',u.BlendMode.BLEND_ADDITIVE),('Premultiplied',u.BlendMode.BLEND_ALPHA_COMPOSITE),('Modulate',u.BlendMode.BLEND_MODULATE),('Water',u.BlendMode.BLEND_OPAQUE),('Terrain',u.BlendMode.BLEND_OPAQUE),('Hair',u.BlendMode.BLEND_MASKED),('Glass',u.BlendMode.BLEND_TRANSLUCENT),('SunGlare',u.BlendMode.BLEND_TRANSLUCENT)]
for label,blend,environment_map in [(label,blend,env)for label,blend in policies for env in ((False,)if label in ('Water','Terrain','SunGlare')else(False,True))]:
  for skin in (False,True):
    name='MW_'+label+('_Env'if environment_map else'')+('_Skin' if skin else '')
    path=D+'/'+name
    m=u.load_asset(path)
    if m is not None and not isinstance(m,u.Material):
        u.EditorAssetLibrary.delete_asset(path);m=None
    if m is None:m=T.create_asset(name,D,u.Material,u.MaterialFactoryNew())
    clear_material(m)
    m.set_editor_property('two_sided',True)
    m.set_editor_property('blend_mode',blend)
    # The original weather-controller pick/vertex alpha owns flare occlusion.
    # Its near-pass overlay must not be clipped a second time by UE world depth.
    m.set_editor_property('disable_depth_test',label=='SunGlare')
    if label in ('Masked','Hair','Foliage'):m.set_editor_property('opacity_mask_clip_value',1/3)
    solid=label in ('Opaque','Masked','Terrain','Hair','Glass','Foliage')
    transparent=label in ('Translucent','Additive','Premultiplied','Modulate','Glass','SunGlare')
    water=label=='Water'
    m.set_editor_property('shading_model',foliage_model if label=='Foliage'else u.MaterialShadingModel.MSM_SINGLE_LAYER_WATER if water else u.MaterialShadingModel.MSM_DEFAULT_LIT if solid else u.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property('tangent_space_normal',False)
    if label=='Glass':
        m.set_editor_property('translucency_lighting_mode',u.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
        m.set_editor_property('screen_space_reflections',True)
    tex=expression(m,u.MaterialExpressionTextureSampleParameter2D,parameter_name='SpriteTexture',texture=u.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
    tex.set_editor_property('mip_value_mode',u.TextureMipValueMode.TMVM_MIP_BIAS)
    tex.set_editor_property('automatic_view_mip_bias',False)
    mip_bias=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeMipBias',default_value=0.)
    link(mip_bias,'',tex,'Bias')
    color=expression(m,u.MaterialExpressionVertexColor)
    tint=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeTint',default_value=u.LinearColor(1,1,1,1))
    vertex_rgb=expression(m,u.MaterialExpressionMultiply);link(color,'',vertex_rgb,'A');link(tint,'',vertex_rgb,'B')
    atmosphere_quality=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeWaterAtmosphere',default_value=1.)
    background_switch=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeBackground',default_value=0.)
    background_active=expression(m,u.MaterialExpressionMultiply);link(background_switch,'',background_active,'A');link(atmosphere_quality,'',background_active,'B')
    # Native rain's emissive material tint is display RGB, like the original
    # sky vertex colour. Decode it once while retaining original texture alpha.
    rain=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeRain',default_value=0.)
    native_colour_active=expression(m,u.MaterialExpressionMax);link(background_active,'',native_colour_active,'A');link(rain,'',native_colour_active,'B')
    fidelity=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeLightingFidelity',default_value=1.)
    fidelity_lit=expression(m,u.MaterialExpressionMultiply)
    # Alpha is coverage; only native display-RGB vertex/material colour decodes.
    # The texture sampler already performs its own sRGB decode.
    lit_colour=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeLit',default_value=1.)
    link(fidelity,'',fidelity_lit,'A');link(lit_colour,'',fidelity_lit,'B')
    colour_active=expression(m,u.MaterialExpressionMax);link(native_colour_active,'',colour_active,'A');link(fidelity_lit,'',colour_active,'B')
    vertex_linear=custom_node(m,'native_atmosphere_color.hlsl',('Color','Active'))
    link(vertex_rgb,'',vertex_linear,'Color');link(colour_active,'',vertex_linear,'Active')
    vertex_alpha=expression(m,u.MaterialExpressionMultiply);link(color,'A',vertex_alpha,'A');link(tint,'A',vertex_alpha,'B')
    stage_uv0=expression(m,u.MaterialExpressionTextureCoordinate,coordinate_index=0)
    stage_uv1=expression(m,u.MaterialExpressionTextureCoordinate,coordinate_index=2)
    stage_uv2=expression(m,u.MaterialExpressionTextureCoordinate,coordinate_index=3)
    stage_samples={}
    for slot in ((0,1,2,3,4,5,6)if environment_map else(0,1,2,4,6)):
        slot_value=expression(m,u.MaterialExpressionConstant,r=slot)
        source=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='SpriteTexture'if slot==0 else f'NativeStage{slot}',texture=u.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
        settings=expression(m,u.MaterialExpressionVectorParameter,parameter_name=f'NativeStage{slot}Settings',default_value=u.LinearColor(0,3,2,0))
        settings4=expression(m,u.MaterialExpressionAppendVector);link(settings,'',settings4,'A');link(settings,'A',settings4,'B')
        sample=custom_node(m,'native_stage_sample.hlsl',('T','UV0','UV1','UV2','Settings','Slot','Bias'));sample.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT4)
        bias=mip_bias if slot==0 else expression(m,u.MaterialExpressionConstant,r=0.)
        for e,n in ((source,'T'),(stage_uv0,'UV0'),(stage_uv1,'UV1'),(stage_uv2,'UV2'),(settings4,'Settings'),(slot_value,'Slot'),(bias,'Bias')):link(e,'',sample,n)
        stage_samples[slot]=sample
    base_rgb=expression(m,u.MaterialExpressionComponentMask,r=True,g=True,b=True);link(stage_samples[0],'',base_rgb,'')
    base_alpha=expression(m,u.MaterialExpressionComponentMask,r=False,g=False,b=False,a=True);link(stage_samples[0],'',base_alpha,'')
    rgb=custom_node(m,'native_stage_colour.hlsl',('A','B','Alpha','Dark','Detail','Decal','Apply','Active'))
    apply_mode=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeTextureApply',default_value=2.)
    stages_active=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeStagesActive',default_value=0.)
    for e,n in ((base_alpha,'Alpha'),(stage_samples[1],'Dark'),(stage_samples[2],'Detail'),(stage_samples[6],'Decal'),(apply_mode,'Apply'),(stages_active,'Active')):link(e,'',rgb,n)
    alpha=expression(m,u.MaterialExpressionMultiply)
    link(base_rgb,'',rgb,'A');link(vertex_linear,'',rgb,'B')
    link(base_alpha,'',alpha,'A');link(vertex_alpha,'',alpha,'B')
    if label=='Terrain':
        # The source terrain decal uses its original vertex-alpha gradient.
        # A ready continuous tile atlas already includes this transition.
        terrain_switch=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeTerrainBlend',default_value=0.)
        source_blend=expression(m,u.MaterialExpressionOneMinus);link(terrain_switch,'',source_blend,'')
        decal_alpha=expression(m,u.MaterialExpressionMultiply);link(vertex_alpha,'',decal_alpha,'A');link(source_blend,'',decal_alpha,'B')
        decal_rgb=expression(m,u.MaterialExpressionComponentMask,r=True,g=True,b=True);link(stage_samples[6],'',decal_rgb,'')
        terrain_decal=expression(m,u.MaterialExpressionAppendVector);link(decal_rgb,'',terrain_decal,'A');link(decal_alpha,'',terrain_decal,'B');link(terrain_decal,'',rgb,'Decal')
    native_opacity=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeBlendOpacity',default_value=1.)
    blend_alpha=expression(m,u.MaterialExpressionLinearInterpolate,const_a=1.)
    link(alpha,'',blend_alpha,'B');link(native_opacity,'',blend_alpha,'Alpha')
    if label!='Opaque' and not water:output(blend_alpha,'',m,u.MaterialProperty.MP_OPACITY_MASK if label in ('Masked','Hair','Foliage') else u.MaterialProperty.MP_OPACITY)
    if skin:
        weights=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='SkinWeights',texture=u.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
        palette=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='BonePalette',texture=u.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
        uv=expression(m,u.MaterialExpressionTextureCoordinate,coordinate_index=1)
        pos=expression(m,u.MaterialExpressionWorldPosition,world_position_shader_offset=u.WorldPositionIncludedOffsets.WPT_EXCLUDE_ALL_SHADER_OFFSETS)
        normal=expression(m,u.MaterialExpressionVertexNormalWS)
        custom=custom_node(m,'native_skin.hlsl',('Weights','Palette','Index','Position','Normal'))
        additional=u.CustomOutput();additional.set_editor_property('output_name','NativeNormal');additional.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT3)
        custom.set_editor_property('additional_outputs',[additional])
        for e,n in ((weights,'Weights'),(palette,'Palette'),(uv,'Index'),(pos,'Position'),(normal,'Normal')):link(e,'',custom,n)
        world_position=expression(m,u.MaterialExpressionAdd)
        link(pos,'',world_position,'A');link(custom,'',world_position,'B')
        normal_node=custom;normal_pin='NativeNormal'
    else:
        world_position=expression(m,u.MaterialExpressionWorldPosition,world_position_shader_offset=u.WorldPositionIncludedOffsets.WPT_EXCLUDE_ALL_SHADER_OFFSETS)
        normal_node=expression(m,u.MaterialExpressionVertexNormalWS);normal_pin=''
    original_world_position=world_position;original_normal=normal_node;original_normal_pin=normal_pin
    view=custom_node(m,'native_view.hlsl',('Position','Normal','Origin','Target','Row0','Row1','Row2','Active','DepthScale'))
    view_normal=u.CustomOutput();view_normal.set_editor_property('output_name','NativeNormal');view_normal.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT3)
    view.set_editor_property('additional_outputs',[view_normal])
    link(world_position,'',view,'Position');link(normal_node,normal_pin,view,'Normal')
    view_parameters={}
    for name,value in (('Origin',(0,0,0,0)),('Target',(0,0,0,0)),('Row0',(1,0,0,0)),('Row1',(0,1,0,0)),('Row2',(0,0,1,0))):
        e=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeView'+name,default_value=u.LinearColor(*value));link(e,'',view,name)
        view_parameters[name]=e
    view_active=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeViewActive',default_value=0.);link(view_active,'',view,'Active')
    depth_scale=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeViewDepthScale',default_value=1.);link(depth_scale,'',view,'DepthScale')
    view_position=expression(m,u.MaterialExpressionAdd);link(world_position,'',view_position,'A');link(view,'',view_position,'B')
    world_position=view_position;normal_node=view;normal_pin='NativeNormal'
    environment=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='NativeEnvironment',texture=u.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
    lit=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeLit',default_value=1.)
    light_mask=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeLightMask',default_value=u.LinearColor(0,0,0,0))
    mask_active=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeLightSetActive',default_value=0.)
    object_sun=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeObjectSun',default_value=1.)
    interior_diffuse=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeInteriorDiffuse',default_value=0.)
    exterior_diffuse=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeExteriorDiffuse',default_value=0.)
    shadowed_diffuse=expression(m,u.MaterialExpressionAdd);link(interior_diffuse,'',shadowed_diffuse,'A');link(exterior_diffuse,'',shadowed_diffuse,'B')
    lighting=custom_node(m,'native_lighting.hlsl',('Environment','Position','Normal','Lit','LightMask','MaskActive','SunActive'))
    for e,n in((light_mask,'LightMask'),(mask_active,'MaskActive'),(object_sun,'SunActive')):link(e,'',lighting,n)
    for e,pin,n in ((environment,'','Environment'),(world_position,'','Position'),(normal_node,normal_pin,'Normal'),(lit,'','Lit')):link(e,pin,lighting,n)
    interpolated=expression(m,u.MaterialExpressionVertexInterpolator)
    link(lighting,'',interpolated,'VS')
    interpolated_normal=expression(m,u.MaterialExpressionVertexInterpolator)
    link(normal_node,normal_pin,interpolated_normal,'VS')
    if solid:
        surface_uv=expression(m,u.MaterialExpressionTextureCoordinate,coordinate_index=0)
        packed=expression(m,u.MaterialExpressionTextureSampleParameter2D,parameter_name='NativeSurfaceDetail',texture=neutral)
        packed.set_editor_property('sampler_type',u.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        strength=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeDetailStrength',default_value=0.)
        quality=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeSurfaceQuality',default_value=1.)
        roughness=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeRoughness',default_value=.82)
        variation=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeRoughnessVariation',default_value=0.)
        detail_position=expression(m,u.MaterialExpressionWorldPosition)
        if label=='Terrain':
            terrain=custom_node(m,'native_terrain.hlsl',('ColorPool','DetailPool','TileMap','Finishes','Layout','Position','BaseRGB','BasePacked','BaseRoughness','BaseSpecular','BaseStrength','BaseVariation','Active','Layers'))
            outputs=[]
            for name,kind in (('PackedOut',u.CustomMaterialOutputType.CMOT_FLOAT4),('RoughnessOut',u.CustomMaterialOutputType.CMOT_FLOAT1),('SpecularOut',u.CustomMaterialOutputType.CMOT_FLOAT1),('StrengthOut',u.CustomMaterialOutputType.CMOT_FLOAT1),('VariationOut',u.CustomMaterialOutputType.CMOT_FLOAT1)):
                item=u.CustomOutput();item.set_editor_property('output_name',name);item.set_editor_property('output_type',kind);outputs.append(item)
            terrain.set_editor_property('additional_outputs',outputs)
            for name,default in (('ColorPool',terrain_arrays['Color']),('DetailPool',terrain_arrays['Detail']),('TileMap',neutral),('Finishes',neutral)):
                value=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='Terrain'+name,texture=default)
                if name!='ColorPool':value.set_editor_property('sampler_type',u.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
                link(value,'',terrain,name)
            layout=expression(m,u.MaterialExpressionVectorParameter,parameter_name='TerrainLayout',default_value=u.LinearColor(0,0,0,0))
            layout4=expression(m,u.MaterialExpressionAppendVector);link(layout,'',layout4,'A');link(layout,'A',layout4,'B');link(layout4,'',terrain,'Layout')
            native_specular=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeSpecular',default_value=.3)
            active=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeTerrainBlend',default_value=0.)
            layers=expression(m,u.MaterialExpressionScalarParameter,parameter_name='TerrainLayers',default_value=0.)
            for e,pin,name in ((detail_position,'','Position'),(base_rgb,'','BaseRGB'),(packed,'RGBA','BasePacked'),(roughness,'','BaseRoughness'),(native_specular,'','BaseSpecular'),(strength,'','BaseStrength'),(variation,'','BaseVariation'),(active,'','Active'),(layers,'','Layers')):link(e,pin,terrain,name)
            link(terrain,'',rgb,'A')
        resolution=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeDetailResolution',default_value=u.LinearColor(512,512,0,0))
        normal_detail=custom_node(m,'native_surface_detail.hlsl',('Packed','Position','UV','Normal','Strength','Quality','Roughness','Variation','Resolution'))
        link(resolution,'',normal_detail,'Resolution')
        outputs=[]
        for name in ('RoughnessOut','Cavity'):
            item=u.CustomOutput();item.set_editor_property('output_name',name);item.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1);outputs.append(item)
        normal_detail.set_editor_property('additional_outputs',outputs)
        for e,pin,n in ((packed,'RGBA','Packed'),(detail_position,'','Position'),(surface_uv,'','UV'),(interpolated_normal,'','Normal'),(strength,'','Strength'),(quality,'','Quality'),(roughness,'','Roughness'),(variation,'','Variation')):link(e,pin,normal_detail,n)
        if label=='Terrain':
            for pin,target in (('PackedOut','Packed'),('RoughnessOut','Roughness'),('StrengthOut','Strength'),('VariationOut','Variation')):link(terrain,pin,normal_detail,target)
    detail=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativePixelLighting',default_value=1.)
    surface_position=expression(m,u.MaterialExpressionWorldPosition)
    surface=custom_node(m,'native_lighting.hlsl',('Environment','Position','Normal','Lit','VertexLighting','Detail','LightMask','MaskActive','SunActive'),prefix='if(Detail<0.5)return VertexLighting;\n')
    for e,n in((light_mask,'LightMask'),(mask_active,'MaskActive'),(object_sun,'SunActive')):link(e,'',surface,n)
    for e,pin,n in ((environment,'','Environment'),(surface_position,'','Position'),(interpolated_normal,'','Normal'),(lit,'','Lit'),(interpolated,'','VertexLighting'),(detail,'','Detail')):link(e,pin,surface,n)
    if solid:
        exterior_normal=expression(m,u.MaterialExpressionLinearInterpolate)
        link(interpolated_normal,'',exterior_normal,'A');link(normal_detail,'',exterior_normal,'B');link(shadowed_diffuse,'',exterior_normal,'Alpha');link(exterior_normal,'',surface,'Normal')
        solar_base=custom_node(m,'native_exterior_colour.hlsl',('Environment','LinearBase','Lighting','Normal','SunActive','Active','Position','LightMask','Exterior'))
        link(exterior_diffuse,'',solar_base,'Exterior')
        native_fill=u.CustomOutput();native_fill.set_editor_property('output_name','AmbientLocal');native_fill.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT3);solar_base.set_editor_property('additional_outputs',[native_fill])
        for e,pin,n in((environment,'','Environment'),(rgb,'','LinearBase'),(surface,'','Lighting'),(exterior_normal,'','Normal'),(object_sun,'','SunActive'),(shadowed_diffuse,'','Active'),(light_mask,'','LightMask')):link(e,pin,solar_base,n)
        link(surface_position,'',solar_base,'Position')
    shaded=expression(m,u.MaterialExpressionMultiply);link(rgb,'',shaded,'A');link(surface,'',shaded,'B')
    emission=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeEmission',default_value=u.LinearColor(0,0,0,1))
    emitted_base=expression(m,u.MaterialExpressionMultiply);link(base_rgb,'',emitted_base,'A');link(emission,'',emitted_base,'B')
    glow_rgb=expression(m,u.MaterialExpressionComponentMask,r=True,g=True,b=True);link(stage_samples[4],'',glow_rgb,'')
    emitted=expression(m,u.MaterialExpressionAdd);link(emitted_base,'',emitted,'A');link(glow_rgb,'',emitted,'B')
    if environment_map:
        native_camera=expression(m,u.MaterialExpressionCameraPositionWS)
        original_camera=expression(m,u.MaterialExpressionLinearInterpolate);link(native_camera,'',original_camera,'A');link(view_parameters['Origin'],'',original_camera,'B');link(view_active,'',original_camera,'Alpha')
        reflect_uv=custom_node(m,'native_environment_uv.hlsl',('Position','Normal','CameraPosition','Row0','Row1'))
        reflect_uv.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT2)
        for e,pin,n in ((original_world_position,'','Position'),(original_normal,original_normal_pin,'Normal'),(original_camera,'','CameraPosition')):link(e,pin,reflect_uv,n)
        for row in (0,1):
            value=expression(m,u.MaterialExpressionVectorParameter,parameter_name=f'NativeEnvRow{row}',default_value=u.LinearColor(0,0,0,0))
            value4=expression(m,u.MaterialExpressionAppendVector);link(value,'',value4,'A');link(value,'A',value4,'B');link(value4,'',reflect_uv,f'Row{row}')
        reflect_interpolated=expression(m,u.MaterialExpressionVertexInterpolator);link(reflect_uv,'',reflect_interpolated,'VS')
        bump_matrix=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeBumpMatrix',default_value=u.LinearColor(0,0,0,0))
        bump_matrix4=expression(m,u.MaterialExpressionAppendVector);link(bump_matrix,'',bump_matrix4,'A');link(bump_matrix,'A',bump_matrix4,'B')
        bump_active=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeBumpActive',default_value=0.)
        perturbed=custom_node(m,'native_environment_bump.hlsl',('UV','Bump','Matrix','Active'));perturbed.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT2)
        for e,n in ((reflect_interpolated,'UV'),(stage_samples[5],'Bump'),(bump_matrix4,'Matrix'),(bump_active,'Active')):link(e,'',perturbed,n)
        reflected_texture=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='NativeEnvironmentMap',texture=u.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
        reflect_settings=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeEnvSettings',default_value=u.LinearColor(0,3,2,0))
        reflect_settings4=expression(m,u.MaterialExpressionAppendVector);link(reflect_settings,'',reflect_settings4,'A');link(reflect_settings,'A',reflect_settings4,'B')
        reflected_sample=custom_node(m,'native_stage_sample.hlsl',('T','UV0','UV1','UV2','Settings','Slot','Bias'));reflected_sample.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT4)
        reflected_slot=expression(m,u.MaterialExpressionConstant,r=7.);reflected_bias=expression(m,u.MaterialExpressionConstant,r=0.)
        for e,n in ((reflected_texture,'T'),(perturbed,'UV0'),(perturbed,'UV1'),(perturbed,'UV2'),(reflect_settings4,'Settings'),(reflected_slot,'Slot'),(reflected_bias,'Bias')):link(e,'',reflected_sample,n)
        reflection_rgb=expression(m,u.MaterialExpressionComponentMask,r=True,g=True,b=True);link(reflected_sample,'',reflection_rgb,'')
        gloss_rgb=expression(m,u.MaterialExpressionComponentMask,r=True,g=True,b=True);link(stage_samples[3],'',gloss_rgb,'')
        reflected_masked=expression(m,u.MaterialExpressionMultiply);link(reflection_rgb,'',reflected_masked,'A');link(gloss_rgb,'',reflected_masked,'B')
        reflected_tinted=expression(m,u.MaterialExpressionMultiply);link(reflected_masked,'',reflected_tinted,'A');link(vertex_linear,'',reflected_tinted,'B')
        with_reflection=expression(m,u.MaterialExpressionAdd);link(emitted,'',with_reflection,'A');link(reflected_tinted,'',with_reflection,'B');emitted=with_reflection
    final_color=expression(m,u.MaterialExpressionAdd);link(shaded,'',final_color,'A');link(emitted,'',final_color,'B')
    modern=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeModernLighting',default_value=1.)
    effect_kind=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeEffectKind',default_value=0.)
    effect_quality=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeEffectQuality',default_value=1.)
    if solid:
        character=custom_node(m,'native_character.hlsl',('Color','Normal','Position','UV','Environment','Kind','Quality','Roughness','Specular','Metallic'))
        character.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1)
        char_outputs=[]
        for name,kind in (('SpecularOut',u.CustomMaterialOutputType.CMOT_FLOAT1),('MetallicOut',u.CustomMaterialOutputType.CMOT_FLOAT1),('AnisotropyOut',u.CustomMaterialOutputType.CMOT_FLOAT1),('WrapOut',u.CustomMaterialOutputType.CMOT_FLOAT3),('TangentOut',u.CustomMaterialOutputType.CMOT_FLOAT3)):
            item=u.CustomOutput();item.set_editor_property('output_name',name);item.set_editor_property('output_type',kind);char_outputs.append(item)
        character.set_editor_property('additional_outputs',char_outputs)
        char_kind=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeCharacterKind',default_value=0.)
        char_quality=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeCharacterQuality',default_value=1.)
        char_spec=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeSpecular',default_value=.3)
        char_metal=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeMetallic',default_value=0.)
        for e,pin,n in ((rgb,'','Color'),(normal_detail,'','Normal'),(surface_position,'','Position'),(surface_uv,'','UV'),(environment,'','Environment'),(char_kind,'','Kind'),(char_quality,'','Quality'),(normal_detail,'RoughnessOut','Roughness'),(char_spec,'','Specular'),(char_metal,'','Metallic')):link(e,pin,character,n)
        if label=='Hair':
            output(character,'AnisotropyOut',m,u.MaterialProperty.MP_ANISOTROPY);output(character,'TangentOut',m,u.MaterialProperty.MP_TANGENT)
        glass=custom_node(m,'native_glass.hlsl',('Normal','Position','CameraPosition','Environment','Kind','Quality','Roughness','Specular'))
        glass_outputs=[]
        for name in ('RoughnessOut','SpecularOut'):
            item=u.CustomOutput();item.set_editor_property('output_name',name);item.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1);glass_outputs.append(item)
        glass.set_editor_property('additional_outputs',glass_outputs)
        glass_camera=expression(m,u.MaterialExpressionCameraPositionWS)
        glass_quality=expression(m,u.MaterialExpressionConstant,r=0.)if environment_map else effect_quality
        for e,pin,n in ((normal_detail,'','Normal'),(surface_position,'','Position'),(glass_camera,'','CameraPosition'),(environment,'','Environment'),(effect_kind,'','Kind'),(glass_quality,'','Quality'),(character,'','Roughness'),(character,'SpecularOut','Specular')):link(e,pin,glass,n)
        ambient=custom_node(m,'native_ambient.hlsl',('Environment','Position','Lit','Probe','Fidelity'))
        link(fidelity,'',ambient,'Fidelity')
        probe_active=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeAmbientProbe',default_value=0.)
        link(probe_active,'',ambient,'Probe')
        for e,n in ((environment,'Environment'),(surface_position,'Position'),(lit,'Lit')):link(e,'',ambient,n)
        ambient_color=expression(m,u.MaterialExpressionMultiply);link(rgb,'',ambient_color,'A');link(ambient,'',ambient_color,'B')
        cavity_color=expression(m,u.MaterialExpressionMultiply);link(ambient_color,'',cavity_color,'A');link(normal_detail,'Cavity',cavity_color,'B');ambient_color=cavity_color
        modern_emission=expression(m,u.MaterialExpressionAdd);link(ambient_color,'',modern_emission,'A');link(emitted,'',modern_emission,'B')
        wrapped=expression(m,u.MaterialExpressionAdd);link(modern_emission,'',wrapped,'A');link(character,'WrapOut',wrapped,'B');modern_emission=wrapped
        glass_emission=expression(m,u.MaterialExpressionAdd);link(modern_emission,'',glass_emission,'A');link(glass,'',glass_emission,'B');modern_emission=glass_emission
        choice=expression(m,u.MaterialExpressionLinearInterpolate)
        link(final_color,'',choice,'A');link(modern_emission,'',choice,'B');link(modern,'',choice,'Alpha')
        final_color=choice
        exterior_fill=expression(m,u.MaterialExpressionMultiply);link(solar_base,'AmbientLocal',exterior_fill,'A');link(normal_detail,'Cavity',exterior_fill,'B')
        exterior_emission=expression(m,u.MaterialExpressionAdd);link(exterior_fill,'',exterior_emission,'A');link(emitted,'',exterior_emission,'B')
        exterior_choice=expression(m,u.MaterialExpressionLinearInterpolate)
        link(final_color,'',exterior_choice,'A');link(exterior_emission,'',exterior_choice,'B');link(shadowed_diffuse,'',exterior_choice,'Alpha');final_color=exterior_choice
    fog=custom_node(m,'native_fog.hlsl',('Environment','Position','CameraPosition','Color','BaseTexture','Fog','Sky','Background','Quality'))
    link(atmosphere_quality,'',fog,'Quality')
    transmission=u.CustomOutput();transmission.set_editor_property('output_name','Transmittance');transmission.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1)
    fog.set_editor_property('additional_outputs',[transmission])
    fog_position=expression(m,u.MaterialExpressionWorldPosition)
    camera_position=expression(m,u.MaterialExpressionCameraPositionWS)
    background=custom_node(m,'native_background.hlsl',('Position','CameraPosition','Background','Origin','Anchored'))
    sky_origin=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeSkyOrigin',default_value=u.LinearColor(0,0,0,0))
    sky_anchored=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeSkyAnchored',default_value=0.)
    link(sky_origin,'',background,'Origin');link(sky_anchored,'',background,'Anchored')
    for e,n in ((world_position,'Position'),(camera_position,'CameraPosition'),(background_switch,'Background')):link(e,'',background,n)
    if skin:
        combined_offset=expression(m,u.MaterialExpressionAdd);link(custom,'',combined_offset,'A');link(background,'',combined_offset,'B')
    else:combined_offset=background
    corrected_offset=expression(m,u.MaterialExpressionAdd);link(combined_offset,'',corrected_offset,'A');link(view,'',corrected_offset,'B')
    if not u.MWBuildLibrary.connect_skin_offset(m,corrected_offset):raise RuntimeError('Native vertex offset connection failed')
    fog_switch=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeFog',default_value=1.)
    sky_switch=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeSky',default_value=0.)
    for e,pin,n in ((environment,'','Environment'),(fog_position,'','Position'),(camera_position,'','CameraPosition'),(final_color,'','Color'),(base_rgb,'','BaseTexture'),(fog_switch,'','Fog'),(sky_switch,'','Sky'),(background_switch,'','Background')):link(e,pin,fog,n)
    celestial_kind=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeCelestialKind',default_value=0.)
    celestial_quality=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeCelestialQuality',default_value=1.)
    celestial=custom_node(m,'native_celestial.hlsl',('Color','Kind','Quality','Visibility'))
    for e,pin,n in ((fog,'','Color'),(celestial_kind,'','Kind'),(celestial_quality,'','Quality'),(fog,'Transmittance','Visibility')):link(e,pin,celestial,n)
    output(celestial,'',m,u.MaterialProperty.MP_EMISSIVE_COLOR)
    if transparent:
        soft=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeSoftParticle',default_value=0.)
        distance=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeSoftDistance',default_value=6.)
        intersection=expression(m,u.MaterialExpressionDepthFade);link(distance,'',intersection,'FadeDistance')
        one=expression(m,u.MaterialExpressionConstant,r=1.);link(one,'',intersection,'Opacity')
        policy=expression(m,u.MaterialExpressionConstant,r={'Translucent':1,'Glass':1,'SunGlare':1,'Additive':2,'Premultiplied':3,'Modulate':4}[label])
        composite=custom_node(m,'native_transparency.hlsl',('Fogged','Unfogged','Transmittance','Opacity','Intersection','Soft','Kind','Quality','Policy','Background'))
        opacity_out=u.CustomOutput();opacity_out.set_editor_property('output_name','OpacityOut');opacity_out.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1);composite.set_editor_property('additional_outputs',[opacity_out])
        for e,pin,n in ((celestial,'','Fogged'),(final_color,'','Unfogged'),(fog,'Transmittance','Transmittance'),(blend_alpha,'','Opacity'),(intersection,'','Intersection'),(soft,'','Soft'),(effect_kind,'','Kind'),(effect_quality,'','Quality'),(policy,'','Policy'),(background_switch,'','Background')):link(e,pin,composite,n)
        output(composite,'',m,u.MaterialProperty.MP_EMISSIVE_COLOR);output(composite,'OpacityOut',m,u.MaterialProperty.MP_OPACITY)
    if water:
        uv0=expression(m,u.MaterialExpressionTextureCoordinate,coordinate_index=0)
        source=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='SpriteTexture',texture=u.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
        planar=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativePlanarWater',default_value=0.)
        water_normal=custom_node(m,'native_water_normal.hlsl',('Surface','UV','Position','Normal','Strength','Quality','Reflection'))
        link(planar,'',water_normal,'Reflection')
        link(atmosphere_quality,'',water_normal,'Quality')
        water_strength=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeWaterBumpStrength',default_value=.55)
        link(water_strength,'',water_normal,'Strength')
        for e,n in ((source,'Surface'),(uv0,'UV'),(surface_position,'Position'),(interpolated_normal,'Normal')):link(e,'',water_normal,n)
        water_roughness=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeWaterRoughness',default_value=.34)
        optical=custom_node(m,'native_water.hlsl',('Environment','Color','Position','CameraPosition','Normal','Quality','Roughness'))
        link(atmosphere_quality,'',optical,'Quality');link(water_roughness,'',optical,'Roughness')
        coefficients=[]
        for name in ('Scattering','Absorption'):
            item=u.CustomOutput();item.set_editor_property('output_name',name);item.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT3);coefficients.append(item)
        item=u.CustomOutput();item.set_editor_property('output_name','RoughnessOut');item.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1);coefficients.append(item)
        optical.set_editor_property('additional_outputs',coefficients)
        for e,n in ((environment,'Environment'),(rgb,'Color'),(surface_position,'Position'),(camera_position,'CameraPosition'),(water_normal,'Normal')):link(e,'',optical,n)
        # The dedicated completed-water post pass applies native fog AFTER SSR.
        output(optical,'',m,u.MaterialProperty.MP_EMISSIVE_COLOR)
        output(water_normal,'',m,u.MaterialProperty.MP_NORMAL)
        base_scale=expression(m,u.MaterialExpressionLinearInterpolate,const_a=.02,const_b=.004);link(atmosphere_quality,'',base_scale,'Alpha')
        base=expression(m,u.MaterialExpressionMultiply);link(rgb,'',base,'A');link(base_scale,'',base,'B');output(base,'',m,u.MaterialProperty.MP_BASE_COLOR)
        cover=expression(m,u.MaterialExpressionLinearInterpolate,const_a=.2,const_b=.025);link(atmosphere_quality,'',cover,'Alpha')
        opacity=expression(m,u.MaterialExpressionMultiply);link(blend_alpha,'',opacity,'A');link(cover,'',opacity,'B');output(opacity,'',m,u.MaterialProperty.MP_OPACITY)
        output(optical,'RoughnessOut',m,u.MaterialProperty.MP_ROUGHNESS)
        spec=expression(m,u.MaterialExpressionLinearInterpolate,const_a=.25,const_b=0.)
        link(planar,'',spec,'Alpha');output(spec,'',m,u.MaterialProperty.MP_SPECULAR)
        output(expression(m,u.MaterialExpressionConstant,r=0.),'',m,u.MaterialProperty.MP_METALLIC)
        volume=expression(m,u.MaterialExpressionSingleLayerWaterMaterialOutput)
        link(optical,'Scattering',volume,'ScatteringCoefficients');link(optical,'Absorption',volume,'AbsorptionCoefficients')
        phase=expression(m,u.MaterialExpressionConstant,r=.2);link(phase,'',volume,'PhaseG')
    if solid:
        # Direct diffuse/specular fade with the same native fog as emissive.
        active=expression(m,u.MaterialExpressionMultiply);link(modern,'',active,'A');link(lit,'',active,'B')
        fade=expression(m,u.MaterialExpressionMultiply);link(active,'',fade,'A');link(fog,'Transmittance',fade,'B')
        base=expression(m,u.MaterialExpressionMultiply);link(rgb,'',base,'A');link(fade,'',base,'B')
        exterior_base=expression(m,u.MaterialExpressionMultiply);link(solar_base,'',exterior_base,'A');link(normal_detail,'Cavity',exterior_base,'B')
        chosen_base=expression(m,u.MaterialExpressionLinearInterpolate);link(rgb,'',chosen_base,'A');link(exterior_base,'',chosen_base,'B');link(shadowed_diffuse,'',chosen_base,'Alpha');link(chosen_base,'',base,'A')
        if label=='Foliage':
            leaf_quality=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeFoliageQuality',default_value=1.)
            transmission=custom_node(m,'native_foliage.hlsl',('Color','Quality','Lighting'))
            for e,n in ((chosen_base,'Color'),(leaf_quality,'Quality'),(fade,'Lighting')):link(e,'',transmission,n)
            output(transmission,'',m,u.MaterialProperty.MP_SUBSURFACE_COLOR)
        if label=='Terrain':
            shore=custom_node(m,'native_shore.hlsl',('Color','Roughness','Position','Environment','Quality'))
            item=u.CustomOutput();item.set_editor_property('output_name','RoughnessOut');item.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1);shore.set_editor_property('additional_outputs',[item])
            for e,pin,n in ((base,'','Color'),(normal_detail,'RoughnessOut','Roughness'),(surface_position,'','Position'),(environment,'','Environment'),(atmosphere_quality,'','Quality')):link(e,pin,shore,n)
            output(shore,'',m,u.MaterialProperty.MP_BASE_COLOR);output(shore,'RoughnessOut',m,u.MaterialProperty.MP_ROUGHNESS)
        else:output(base,'',m,u.MaterialProperty.MP_BASE_COLOR)
        output(normal_detail,'',m,u.MaterialProperty.MP_NORMAL)
        output(normal_detail,'Cavity',m,u.MaterialProperty.MP_AMBIENT_OCCLUSION)
        if label!='Terrain':output(glass,'RoughnessOut',m,u.MaterialProperty.MP_ROUGHNESS)
        for parameter,value,prop in [('NativeSpecular',.3,u.MaterialProperty.MP_SPECULAR),('NativeMetallic',0.,u.MaterialProperty.MP_METALLIC)]:
            node=expression(m,u.MaterialExpressionScalarParameter,parameter_name=parameter,default_value=value)
            pin=''
            if label!='Terrain':node=character;pin='SpecularOut'if parameter=='NativeSpecular'else'MetallicOut'
            if label!='Terrain' and parameter=='NativeSpecular':node=glass;pin='SpecularOut'
            if label=='Terrain' and parameter=='NativeSpecular':node=terrain;pin='SpecularOut'
            if parameter!='NativeRoughness':
                scaled=expression(m,u.MaterialExpressionMultiply);link(node,pin,scaled,'A');link(fade,'',scaled,'B');node=scaled
            output(node,'',m,prop)
    alpha_settings=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeAlphaTest',default_value=u.LinearColor(0,0,0,0))
    if transparent:
        alpha_clip=custom_node(m,'native_alpha_test.hlsl',('Color','Alpha','Settings'))
        link(composite,'',alpha_clip,'Color');link(alpha,'',alpha_clip,'Alpha');link(alpha_settings,'',alpha_clip,'Settings')
        output(alpha_clip,'',m,u.MaterialProperty.MP_EMISSIVE_COLOR)
    if label in ('Masked','Hair','Foliage'):
        alpha_coverage=custom_node(m,'native_alpha_coverage.hlsl',('Alpha','Opacity','Settings'));alpha_coverage.set_editor_property('output_type',u.CustomMaterialOutputType.CMOT_FLOAT1)
        for e,n in ((alpha,'Alpha'),(blend_alpha,'Opacity'),(alpha_settings,'Settings')):link(e,'',alpha_coverage,n)
        output(alpha_coverage,'',m,u.MaterialProperty.MP_OPACITY_MASK)
    L.set_material_usage(m,u.MaterialUsage.MATUSAGE_INSTANCED_STATIC_MESHES)
    L.recompile_material(m)
    if not u.EditorAssetLibrary.save_loaded_asset(m,False):raise RuntimeError('Unable to save '+path)
name='MW_NativeAttenuation';path=D+'/'+name
attenuation_material=u.load_asset(path)
if attenuation_material is None:attenuation_material=T.create_asset(name,D,u.Material,u.MaterialFactoryNew())
clear_material(attenuation_material)
attenuation_material.set_editor_property('material_domain',u.MaterialDomain.MD_LIGHT_FUNCTION)
position=expression(attenuation_material,u.MaterialExpressionWorldPosition)
light_position=expression(attenuation_material,u.MaterialExpressionVectorParameter,parameter_name='NativeLightPosition',default_value=u.LinearColor(0,0,0,256))
position4=expression(attenuation_material,u.MaterialExpressionAppendVector);link(light_position,'',position4,'A');link(light_position,'A',position4,'B')
curve=expression(attenuation_material,u.MaterialExpressionVectorParameter,parameter_name='NativeLightCurve',default_value=u.LinearColor(1,0,0,1))
curve4=expression(attenuation_material,u.MaterialExpressionAppendVector);link(curve,'',curve4,'A');link(curve,'A',curve4,'B')
attenuation=custom_node(attenuation_material,'native_attenuation.hlsl',('Position','LightPosition','Curve'))
for e,n in((position,'Position'),(position4,'LightPosition'),(curve4,'Curve')):link(e,'',attenuation,n)
output(attenuation,'',attenuation_material,u.MaterialProperty.MP_EMISSIVE_COLOR)
L.recompile_material(attenuation_material)
if not u.EditorAssetLibrary.save_loaded_asset(attenuation_material,False):raise RuntimeError('Native attenuation material could not be saved')
name='MW_WaterFog';path=D+'/'+name
m=u.load_asset(path)
if m is None:m=T.create_asset(name,D,u.Material,u.MaterialFactoryNew())
clear_material(m)
m.set_editor_property('material_domain',u.MaterialDomain.MD_POST_PROCESS)
m.set_editor_property('blendable_location',u.BlendableLocation.BL_BEFORE_TONEMAPPING)
node=custom_node(m,'native_water_fog.hlsl',('FogColor','FogRange','Scene','Depth','WaterDepth','Stencil','Active','Quality','Planar','ReflectionTexture','Origin','Right','Up','Forward','Lens','Sky','Position','CameraPosition','Normal','BottomDepth','Exterior'))
planar=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativePlanarWater',default_value=0.);link(planar,'',node,'Planar')
reflection=expression(m,u.MaterialExpressionTextureObjectParameter,parameter_name='NativeWaterReflection',texture=neutral)
reflection.set_editor_property('sampler_type',u.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR);link(reflection,'',node,'ReflectionTexture')
for name,value in (('Origin',(0,0,0,0)),('Right',(0,1,0,0)),('Up',(0,0,1,0)),('Forward',(1,0,0,0)),('Lens',(1,1,0,0)),('Sky',(0,0,0,0))):
    e=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeReflection'+name,default_value=u.LinearColor(*value));link(e,'',node,name)
position=expression(m,u.MaterialExpressionWorldPosition);link(position,'',node,'Position')
camera=expression(m,u.MaterialExpressionCameraPositionWS);link(camera,'',node,'CameraPosition')
normal=expression(m,u.MaterialExpressionSceneTexture,scene_texture_id=u.SceneTextureId.PPI_WORLD_NORMAL)
mask=expression(m,u.MaterialExpressionComponentMask,r=True,g=True,b=True);link(normal,'Color',mask,'');link(mask,'',node,'Normal')
bottom=expression(m,u.MaterialExpressionSceneDepthWithoutWater,fallback_depth=0.);link(bottom,'',node,'BottomDepth')
quality=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeWaterAtmosphere',default_value=1.);link(quality,'',node,'Quality')
# UE's reusable post-process MID copies texture overrides via CopyInterpParameters
# and numeric values via CopyScalarAndVectorParameters. Keep fog numeric and the
# explicitly linear HDR reflection target as a texture override.
for name,default in (('FogColor',u.LinearColor(0,0,0,1)),('FogRange',u.LinearColor(0,1,0,0))):
    value=expression(m,u.MaterialExpressionVectorParameter,parameter_name='NativeWater'+name,default_value=default)
    if name=='FogRange':
        combined=expression(m,u.MaterialExpressionAppendVector)
        link(value,'',combined,'A');link(value,'A',combined,'B');value=combined
    link(value,'',node,name)
exterior_fog=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeExteriorFog',default_value=0.);link(exterior_fog,'',node,'Exterior')
active=expression(m,u.MaterialExpressionScalarParameter,parameter_name='NativeWaterFogActive',default_value=1.)
link(active,'',node,'Active')
for identity,pin in ((u.SceneTextureId.PPI_POST_PROCESS_INPUT0,'Scene'),(u.SceneTextureId.PPI_SCENE_DEPTH,'Depth'),(u.SceneTextureId.PPI_CUSTOM_DEPTH,'WaterDepth'),(u.SceneTextureId.PPI_CUSTOM_STENCIL,'Stencil')):
    sample=expression(m,u.MaterialExpressionSceneTexture,scene_texture_id=identity)
    mask=expression(m,u.MaterialExpressionComponentMask,r=True,g=pin=='Scene',b=pin=='Scene')
    link(sample,'Color',mask,'');sample=mask
    link(sample,'',node,pin)
output(node,'',m,u.MaterialProperty.MP_EMISSIVE_COLOR)
L.recompile_material(m)
if not u.EditorAssetLibrary.save_loaded_asset(m,False):raise RuntimeError('Unable to save '+path)
u.log('UEMW generated forty surface materials and completed-water fog successfully')

