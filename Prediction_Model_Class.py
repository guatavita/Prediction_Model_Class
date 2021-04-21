import sys, shutil
from threading import Thread
from multiprocessing import cpu_count
from queue import *
import time
from functools import partial
from Utils import cleanout_folder, weighted_categorical_crossentropy
from Utils import plot_scroll_Image, down_folder
from Bilinear_Dsc import BilinearUpsampling
from Image_Processing import template_dicom_reader, Ensure_Liver_Segmentation, Ensure_Liver_Disease_Segmentation, \
    PredictDiseaseAblation, PredictLobes, BaseModelBuilder
from Image_Processors_Module.src.Processors.MakeTFRecordProcessors import *


def copy_files(A, q, dicom_folder, input_path, thread_count):
    threads = []
    for worker in range(thread_count):
        t = Thread(target=worker_def, args=(A,))
        t.start()
        threads.append(t)
    image_list = os.listdir(dicom_folder)
    for file in image_list:
        item = {'dicom_folder': dicom_folder, 'local_folder': input_path, 'file': file}
        q.put(item)
    for i in range(thread_count):
        q.put(None)
    for t in threads:
        t.join()


class Copy_Files(object):
    def process(self, dicom_folder, local_folder, file):
        input_path = os.path.join(local_folder, file)
        while not os.path.exists(input_path):
            try:
                shutil.copy2(os.path.join(dicom_folder, file), input_path)
            except:
                print('Connection dropped...')
                if os.path.exists(input_path):
                    os.remove(input_path)
        return None


def worker_def(A):
    q = A[0]
    base_class = Copy_Files()
    while True:
        item = q.get()
        if item is None:
            break
        else:
            try:
                base_class.process(**item)
            except:
                print('Failed')
            q.task_done()


def find_base_dir():
    base_path = '.'
    for _ in range(20):
        if 'Morfeus' in os.listdir(base_path):
            break
        else:
            base_path = os.path.join(base_path, '..')
    return base_path


def run_model():
    with tf.device('/gpu:0'):
        gpu_options = tf.compat.v1.GPUOptions(allow_growth=True)
        sess = tf.compat.v1.Session(config=tf.compat.v1.ConfigProto(
            gpu_options=gpu_options, log_device_placement=False))
        tf.compat.v1.keras.backend.set_session(sess)
        models_info = {}
        try:
            os.listdir('\\\\mymdafiles\\di_data1\\')
            morfeus_path = '\\\\mymdafiles\\di_data1\\'
            shared_drive_path = '\\\\mymdafiles\\ro-ADMIN\\SHARED\\Radiation physics\\BMAnderson\\Auto_Contour_Sites\\'
            raystation_clinical_path = '\\\\mymdafiles\\ou-radonc\\Raystation\\Clinical\\Auto_Contour_Sites\\'
            model_load_path = os.path.join(morfeus_path, 'Morfeus', 'Auto_Contour_Sites', 'Models')
            raystation_research_path = '\\\\mymdafiles\\ou-radonc\\Raystation\\Research\\Auto_Contour_Sites\\'
        except:
            desktop_path = find_base_dir()
            morfeus_path = os.path.join(desktop_path)
            model_load_path = os.path.join(desktop_path, 'Auto_Contour_Models')
            shared_drive_path = os.path.abspath(os.path.join(desktop_path, 'Shared_Drive', 'Auto_Contour_Sites'))
            raystation_clinical_path = os.path.abspath(
                os.path.join(desktop_path, 'Raystation_LDrive', 'Clinical', 'Auto_Contour_Sites'))
            raystation_research_path = os.path.abspath(
                os.path.join(desktop_path, 'Raystation_LDrive', 'Research', 'Auto_Contour_Sites'))
        '''
        Liver Model
        '''
        liver_model = BaseModelBuilder(image_key='image',
                                       model_path=os.path.join(model_load_path,
                                                               'Liver',
                                                               'weights-improvement-512_v3_model_xception-36.hdf5'),
                                       Bilinear_model=BilinearUpsampling, loss=None, loss_weights=None)
        paths = [
                # r'H:\AutoModels\Liver\Input_4',
                os.path.join(morfeus_path, 'Morfeus', 'BMAnderson', 'Test', 'Input_4'),
                os.path.join(shared_drive_path, 'Liver_Auto_Contour', 'Input_3'),
                os.path.join(morfeus_path, 'Morfeus', 'Auto_Contour_Sites', 'Liver_Auto_Contour', 'Input_3'),
                os.path.join(raystation_clinical_path, 'Liver_Auto_Contour', 'Input_3'),
                os.path.join(raystation_research_path, 'Liver_Auto_Contour', 'Input_3')
            ]
        liver_model.set_paths(paths)
        liver_model.set_image_processors([
                Threshold_Images(image_keys=('image',), lower_bound=-100, upper_bound=300),
                AddByValues(image_keys=('image',), values=(100,)),
                DivideByValues(image_keys=('image', 'image'), values=(400, 1/255)),
                ExpandDimensions(axis=-1, image_keys=('image',)),
                RepeatChannel(num_repeats=3, axis=-1, image_keys=('image',)),
                Ensure_Image_Proportions(image_rows=512, image_cols=512, image_keys=('image',),
                                         post_process_keys=('image', 'prediction')),
                VGGNormalize(image_keys=('image',))])
        liver_model.set_prediction_processors([
            Threshold_Prediction(threshold=0.5, single_structure=True, is_liver=True, prediction_keys=('prediction',))])
        liver_model.set_dicom_reader(template_dicom_reader(roi_names=['Liver_BMA_Program_4']))
        models_info['liver'] = liver_model
        '''
        Parotid Model
        '''
        partotid_model = {'model_path': os.path.join(model_load_path, 'Parotid', 'whole_model'),
                          'roi_names': ['Parotid_L_BMA_Program_4', 'Parotid_R_BMA_Program_4'],
                          'dicom_paths': [  # os.path.join(shared_drive_path,'Liver_Auto_Contour','Input_3')
                              os.path.join(morfeus_path, 'Morfeus', 'Auto_Contour_Sites', 'Parotid_Auto_Contour',
                                           'Input_3'),
                              os.path.join(raystation_clinical_path, 'Parotid_Auto_Contour', 'Input_3'),
                              os.path.join(raystation_research_path, 'Parotid_Auto_Contour', 'Input_3')
                          ],
                          'file_loader': template_dicom_reader(roi_names=None),
                          'image_processors': [NormalizeParotidMR(image_keys=('image',)),
                                               ExpandDimensions(axis=-1, image_keys=('image',)),
                                               RepeatChannel(num_repeats=3, axis=-1, image_keys=('image',)),
                                               Ensure_Image_Proportions(image_rows=256, image_cols=256,
                                                                        image_keys=('image',),
                                                                        post_process_keys=('image', 'prediction')),
                                               ],
                          'prediction_processors': [
                              # Turn_Two_Class_Three(),
                              Threshold_and_Expand(seed_threshold_value=0.9,
                                                   lower_threshold_value=.5),
                              Fill_Binary_Holes(prediction_key='prediction', dicom_handle_key='primary_handle')]
                          }
       # models_info['parotid'] = return_model_info(**partotid_model)
        '''
        Lung Model
        '''
        lung_model = BaseModelBuilder(image_key='image',
                                      model_path=os.path.join(model_load_path, 'Lungs', 'Covid_Four_Model_50'),
                                      Bilinear_model=BilinearUpsampling, loss=None, loss_weights=None)
        lung_model.set_dicom_reader(template_dicom_reader(roi_names=['Ground Glass_BMA_Program_2',
                                                                     'Lung_BMA_Program_2']))
        lung_model.set_paths([
                    # r'H:\AutoModels\Lung\Input_4',
                    os.path.join(shared_drive_path, 'Lungs_Auto_Contour', 'Input_3'),
                    os.path.join(morfeus_path, 'Morfeus', 'Auto_Contour_Sites', 'Lungs', 'Input_3'),
                    os.path.join(raystation_clinical_path, 'Lungs_Auto_Contour', 'Input_3'),
                    os.path.join(raystation_research_path, 'Lungs_Auto_Contour', 'Input_3'),
                    os.path.join(morfeus_path, 'Morfeus', 'BMAnderson', 'Test', 'Input_3')
                ])
        lung_model.set_image_processors([
                          AddByValues(image_keys=('image',), values=(751,)),
                          DivideByValues(image_keys=('image',), values=(200,)),
                          Threshold_Images(image_keys=('image',), lower_bound=-5, upper_bound=5),
                          DivideByValues(image_keys=('image',), values=(5,)),
                          ExpandDimensions(axis=-1, image_keys=('image',)),
                          RepeatChannel(num_repeats=3, axis=-1, image_keys=('image',)),
                          Ensure_Image_Proportions(image_rows=512, image_cols=512, image_keys=('image',),
                                                   post_process_keys=('image', 'prediction')),
                      ])
        lung_model.set_prediction_processors([
                          ArgMax(image_keys=('prediction',), axis=-1),
                          To_Categorical(num_classes=3, annotation_keys=('prediction',)),
                          CombineLungLobes(prediction_key='prediction', dicom_handle_key='primary_handle')
                      ])
        models_info['lungs'] = lung_model
        '''
        Liver Lobe Model
        '''
        liver_lobe_model = PredictLobes(image_key='image', loss=partial(weighted_categorical_crossentropy),
                                        loss_weights=[0.14, 10, 7.6, 5.2, 4.5, 3.8, 5.1, 4.4, 2.7],
                                        model_path=os.path.join(model_load_path, 'Liver_Lobes', 'Model_397'),
                                        Bilinear_model=BilinearUpsampling)
        liver_lobe_model.set_dicom_reader(Ensure_Liver_Segmentation(wanted_roi='Liver_BMA_Program_4',
                                                                    liver_folder=os.path.join(raystation_clinical_path,
                                                                                              'Liver_Auto_Contour',
                                                                                              'Input_3'),
                                                                    associations={
                                                                        'Liver_BMA_Program_4': 'Liver_BMA_Program_4',
                                                                        'Liver': 'Liver_BMA_Program_4'},
                                                                    roi_names=['Liver_Segment_{}_BMAProgram3'.format(i)
                                                                               for i in range(1, 5)] +
                                                                              ['Liver_Segment_5-8_BMAProgram3']))
        liver_lobe_model.set_paths([
                                # r'H:\AutoModels\Lobes\Input_4',
                                os.path.join(morfeus_path, 'Morfeus', 'Auto_Contour_Sites',
                                             'Liver_Segments_Auto_Contour', 'Input_3'),
                                os.path.join(raystation_clinical_path, 'Liver_Segments_Auto_Contour', 'Input_3'),
                                os.path.join(raystation_research_path, 'Liver_Segments_Auto_Contour', 'Input_3'),
                            ])
        liver_lobe_model.set_image_processors([
            Normalize_to_annotation(image_key='image', annotation_key='annotation', annotation_value_list=(1,)),
            Ensure_Image_Proportions(image_rows=512, image_cols=512, image_keys=('image', 'annotation')),
            CastData(image_keys=('image', 'annotation'), dtypes=('float32', 'int')),
            AddSpacing(spacing_handle_key='primary_handle'),
            DeepCopyKey(from_keys=('annotation',), to_keys=('og_annotation',)),
            Resampler(resample_keys=('image', 'annotation'), resample_interpolators=('Linear', 'Nearest'),
                      desired_output_spacing=[None, None, 5.0], post_process_resample_keys=('prediction',),
                      post_process_original_spacing_keys=('primary_handle',), post_process_interpolators=('Linear',)),
            Box_Images(bounding_box_expansion=(10, 10, 10), image_key='image', annotation_key='annotation',
                       wanted_vals_for_bbox=(1,), power_val_z=64, power_val_r=320, power_val_c=384,
                       post_process_keys=('image', 'annotation', 'prediction'), pad_value=0),
            ExpandDimensions(image_keys=('image', 'annotation'), axis=0),
            ExpandDimensions(image_keys=('image', 'annotation', 'og_annotation'), axis=-1),
            Threshold_Images(image_keys=('image',), lower_bound=-5, upper_bound=5),
            DivideByValues(image_keys=('image',), values=(10,)),
            MaskOneBasedOnOther(guiding_keys=('annotation',), changing_keys=('image',), guiding_values=(0,),
                                mask_values=(0,)),
            CreateTupleFromKeys(image_keys=('image', 'annotation'), output_key='combined'),
            SqueezeDimensions(post_prediction_keys=('image', 'annotation', 'prediction'))
        ])
        liver_lobe_model.set_prediction_processors([
            MaskOneBasedOnOther(guiding_keys=('og_annotation',), changing_keys=('prediction',), guiding_values=(0,),
                                mask_values=(0,)),
            SqueezeDimensions(image_keys=('og_annotation',)),
            Threshold_and_Expand_New(seed_threshold_value=[.9, .9, .9, .9, .9],
                                     lower_threshold_value=[.75, .9, .25, .2, .75],
                                     prediction_key='prediction', ground_truth_key='og_annotation',
                                     dicom_handle_key='primary_handle')
        ])
        models_info['liver_lobes'] = liver_lobe_model
        '''
        Disease Ablation Model
        '''
        liver_disease = PredictDiseaseAblation(image_key='combined',
                                               model_path=os.path.join(model_load_path,
                                                                       'Liver_Disease_Ablation',
                                                                       'Model_42'),
                                               Bilinear_model=BilinearUpsampling, loss_weights=None, loss=None)
        liver_disease.set_paths([
                          # r'H:\AutoModels\Liver_Disease\Input_3',
                          os.path.join(morfeus_path, 'Morfeus', 'Auto_Contour_Sites',
                                       'Liver_Disease_Ablation_Auto_Contour', 'Input_3'),
                          os.path.join(raystation_clinical_path, 'Liver_Disease_Ablation_Auto_Contour', 'Input_3'),
                          os.path.join(raystation_research_path, 'Liver_Disease_Ablation_Auto_Contour', 'Input_3'),
                          os.path.join(morfeus_path, 'Morfeus', 'BMAnderson', 'Test', 'Input_5')
                      ])
        liver_disease.set_image_processors([
                DeepCopyKey(from_keys=('annotation',), to_keys=('og_annotation',)),
                Normalize_to_annotation(image_key='image', annotation_key='annotation',
                                        annotation_value_list=(1,), mirror_max=True),
                AddSpacing(spacing_handle_key='primary_handle'),
                Resampler(resample_keys=('image', 'annotation'),
                          resample_interpolators=('Linear', 'Nearest'),
                          desired_output_spacing=[None, None, 1.0],
                          post_process_resample_keys=('prediction',),
                          post_process_original_spacing_keys=('primary_handle',),
                          post_process_interpolators=('Linear',)),
                Box_Images(bounding_box_expansion=(5, 20, 20), image_key='image',
                           annotation_key='annotation', wanted_vals_for_bbox=(1,),
                           power_val_z=2 ** 4, power_val_r=2 ** 5, power_val_c=2 ** 5),
                Threshold_Images(lower_bound=-10, upper_bound=10, divide=True, image_keys=('image',)),
                ExpandDimensions(image_keys=('image', 'annotation'), axis=0),
                ExpandDimensions(image_keys=('image', 'annotation'), axis=-1),
                MaskOneBasedOnOther(guiding_keys=('annotation',),
                                    changing_keys=('image',),
                                    guiding_values=(0,),
                                    mask_values=(0,)),
                CombineKeys(image_keys=('image', 'annotation'), output_key='combined'),
                SqueezeDimensions(post_prediction_keys=('image', 'annotation', 'prediction'))
        ])
        liver_disease.set_dicom_reader(Ensure_Liver_Disease_Segmentation(wanted_roi='Liver_BMA_Program_4',
                                                                         roi_names=['Liver_Disease_Ablation_BMA_Program_0'],
                                                                         liver_folder=os.path.join(raystation_clinical_path,
                                                                                                   'Liver_Auto_Contour',
                                                                                                   'Input_3'),
                                                                         associations={
                                                                             'Liver_BMA_Program_4': 'Liver_BMA_Program_4',
                                                                             'Liver': 'Liver_BMA_Program_4'}))
        liver_disease.set_prediction_processors([
            Threshold_and_Expand(seed_threshold_value=0.55, lower_threshold_value=.3, prediction_key='prediction'),
            Fill_Binary_Holes(prediction_key='prediction', dicom_handle_key='primary_handle'),
            ExpandDimensions(image_keys=('og_annotation',), axis=-1),
            MaskOneBasedOnOther(guiding_keys=('og_annotation',), changing_keys=('prediction',),
                                guiding_values=(0,), mask_values=(0,)),
            MinimumVolumeandAreaPrediction(min_volume=0.25, prediction_key='prediction',
                                           dicom_handle_key='primary_handle')
        ])
        models_info['liver_disease'] = liver_disease
        all_sessions = {}
        graph = tf.compat.v1.Graph()
        model_keys = ['liver_lobes', 'liver', 'lungs', 'liver_disease']  # liver_lobes
        # model_keys = ['liver', 'lungs', 'liver_lobes']
        with graph.as_default():
            gpu_options = tf.compat.v1.GPUOptions(allow_growth=True)
            for key in model_keys:
                session = tf.compat.v1.Session(config=tf.compat.v1.ConfigProto(
                    gpu_options=gpu_options, log_device_placement=False))
                with session.as_default():
                    tf.compat.v1.keras.backend.set_session(session)
                    model_info = models_info[key]
                    model_info.build_model(graph=graph, session=session)
                    all_sessions[key] = session
        # g.finalize()
        running = True
        print('running')
        attempted = {}
        input_path = os.path.join('.', 'Input_Data')
        thread_count = int(cpu_count() * 0.1 + 1)
        if not os.path.exists(input_path):
            os.makedirs(input_path)
        q = Queue(maxsize=thread_count)
        A = [q, ]
        while running:
            with graph.as_default():
                for key in model_keys:
                    model_runner = models_info[key]
                    with all_sessions[key].as_default():
                        tf.compat.v1.keras.backend.set_session(all_sessions[key])
                        for path in model_runner.paths:
                            if not os.path.exists(path):
                                continue
                            dicom_folder_all_out = down_folder(path, [])
                            for dicom_folder in dicom_folder_all_out:
                                if os.path.exists(os.path.join(dicom_folder, '..', 'Raystation_Export.txt')):
                                    os.remove(os.path.join(dicom_folder, '..', 'Raystation_Export.txt'))
                                true_outpath = None
                                print(dicom_folder)
                                if dicom_folder not in attempted.keys():
                                    attempted[dicom_folder] = 0
                                else:
                                    attempted[dicom_folder] += 1
                                try:
                                    cleanout_folder(path_origin=input_path, dicom_dir=input_path, delete_folders=False)
                                    copy_files(q=q, A=A, dicom_folder=dicom_folder, input_path=input_path,
                                               thread_count=thread_count)
                                    input_features = {'input_path': input_path, 'dicom_folder': dicom_folder}
                                    input_features = model_runner.load_images(input_features)
                                    print('Got images')
                                    output = os.path.join(path.split('Input_')[0], 'Output')
                                    series_instances_dictionary = model_runner.return_series_instance_dictionary()
                                    series_instance_uid = series_instances_dictionary['SeriesInstanceUID']
                                    patientID = series_instances_dictionary['PatientID']
                                    true_outpath = os.path.join(output, patientID, series_instance_uid)
                                    input_features['out_path'] = true_outpath
                                    preprocessing_status = os.path.join(true_outpath, 'Status_Preprocessing.txt')
                                    if not os.path.exists(true_outpath):
                                        os.makedirs(true_outpath)
                                    if not model_runner.return_status():
                                        cleanout_folder(path_origin=input_path, dicom_dir=input_path,
                                                        delete_folders=False)
                                        fid = open(os.path.join(true_outpath, 'Failed.txt'), 'w+')
                                        fid.close()
                                        continue
                                    fid = open(preprocessing_status, 'w+')
                                    fid.close()
                                    input_features = model_runner.pre_process(input_features)
                                    os.remove(preprocessing_status)
                                    cleanout_folder(path_origin=input_path, dicom_dir=input_path, delete_folders=False)
                                    predicting_status = os.path.join(true_outpath, 'Status_Predicting.txt')
                                    fid = open(predicting_status, 'w+')
                                    fid.close()
                                    k = time.time()
                                    input_features = model_runner.predict(input_features)
                                    print('Prediction took ' + str(time.time() - k) + ' seconds')
                                    os.remove(predicting_status)
                                    post_processing_status = os.path.join(true_outpath, 'Status_Postprocessing.txt')

                                    fid = open(post_processing_status, 'w+')
                                    fid.close()
                                    input_features = model_runner.post_process(input_features)
                                    print('Post Processing')
                                    input_features = model_runner.prediction_process(input_features)
                                    os.remove(post_processing_status)

                                    writing_status = os.path.join(true_outpath, 'Status_Writing RT Structure.txt')
                                    fid = open(writing_status, 'w+')
                                    fid.close()
                                    model_runner.write_predictions(input_features)
                                    print('RT structure ' + patientID + ' printed to ' +
                                          os.path.join(output, patientID, series_instance_uid) +
                                          ' with name: RS_MRN' + patientID + '.dcm')
                                    os.remove(writing_status)
                                    cleanout_folder(path_origin=path, dicom_dir=dicom_folder, delete_folders=True)
                                    attempted[dicom_folder] = -1
                                except:
                                    if attempted[dicom_folder] <= 1:
                                        attempted[dicom_folder] += 1
                                        print('Failed once.. trying again')
                                        continue
                                    else:
                                        try:
                                            print('Failed twice')
                                            cleanout_folder(path_origin=path, dicom_dir=dicom_folder,
                                                            delete_folders=True)
                                            if true_outpath is not None:
                                                if not os.path.exists(true_outpath):
                                                    os.makedirs(true_outpath)
                                            print('had an issue')
                                            fid = open(os.path.join(true_outpath, 'Failed.txt'), 'w+')
                                            fid.close()
                                        except:
                                            xxx = 1
                                        continue
            time.sleep(1)


if __name__ == '__main__':
    pass
