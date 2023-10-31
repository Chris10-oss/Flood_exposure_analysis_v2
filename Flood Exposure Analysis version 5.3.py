#Flood Exposure Analysis version 5.3
#primary author: Robert Berstch
#secondary author: Christos Iliadis
#host: Newcastle University

#libraries required
import os
import rtree
import re
from shapely.geometry import shape, Point
import datetime
import pandas as pd
import geopandas as gpd
import warnings
from operator import itemgetter
import ipywidgets as widgets
from IPython.display import display

folder_input = "Copy the folder path with the flood depth file or files"
builds_input = "Copy the file path with the buildings shapefile"

cols_list = []
builds_df1 = gpd.read_file(builds_input)
for n in builds_df1.columns:
    cols_list.append(n)
    
#import the field of buildings
builds_field = "UID" #check the field from the shapefile

buffer_value = 150 #check the grid resolution

def process_data(ev):
    
    T_start = datetime.datetime.now()
    builds_file = builds_input
    input_folder = folder_input
    
    if not os.path.exists(os.path.dirname(input_folder) + '/Exposure_Outputs'):
        os.makedirs(os.path.dirname(input_folder) + '/Exposure_Outputs')
        
    #Creating the spatial index with the rtree module is only done for ine depth file using X,Y only
    print('..creating spatial index..')
    file_count = sorted([f for f in os.listdir(input_folder) if os.path.isfile(input_folder + '/' + f)])
    
    #first get the resolution of the grid:
    df_res = pd.read_csv(input_folder + '/' + file_count[0], nrows = 3)
    xdiff = df_res.iloc[2, 0] - df_res.iloc[1, 0]
    ydiff = df_res.iloc[2, 1] - df_res.iloc[1, 1]
    if xdiff != 0:
        dx = xdiff
    elif xdiff == 0:
        dx = ydiff
    del(df_res)
    buffer_distance = ((buffer_value)/100) * dx # in % grid resolution
    
    x = []
    y = []
    with open(input_folder + '/' + file_count[0], 'r') as t:
        aline = t.readline().strip()
        aline = t.readline()
        while aline != '':
            column = re.split('\s|\s\s|\t|,',str(aline))
            x.append(float(column[0]))
            y.append(float(column[1]))
            aline = t.readline()
    t.close()
    
    cell_idx = []
    for idx, xi in enumerate(x):
        cell_idx.append(idx)
        
    index = rtree.index.Index() #create the spatial index
    for pt_idx, xi, yi in zip(cell_idx, x, y):
        index.insert(pt_idx, (xi, yi))
        
    del(cell_idx)
    
    cell_index = []
    buffer_list = []
    builds = gpd.GeoDataFrame.from_file((builds_file))
    builds_n = len(builds)
    builds_df = gpd.GeoDataFrame(builds[[str(builds_field), 'geometry']])
    del(builds)
    
    for b_id, b_geom in zip(builds_df[str(builds_field)], builds_df['geometry']):
        buffer = shape(b_geom.buffer(float(buffer_distance), resolution=10)) #create a buffer polygon for the building polygons from resolution 10 to 16
        for cell in list(index.intersection(buffer.bounds)): #first check if the point is within the bounding box of a building buffer
            cell_int = Point(x[cell], y[cell])  
            if cell_int.intersects(buffer): #then check if the point intersects with buffer polygon
                buffer_list.append(b_id) #store the building ID
                cell_index.append(cell) #store the line inedex of the intersecting points
                
    df_b = pd.DataFrame(list(zip(buffer_list, cell_index)), columns = [str(builds_field), 'cell'])
    df_b = df_b.sort_values(by = ['cell'])
    print('spatial index created')
    
    #------------------------------------------------------------------------------reading depth files 
        
    files = file_count
    
    for i, filename in enumerate(files):
        f = open(input_folder + '/' + filename)
        print('processing file: ' + str(filename))
        Z=[]
        aline = f.readline().strip()       
        aline = f.readline()
        while aline != '':
            column = re.split('\s|\s\s|\t|,',str(aline))
            Z.append(float(column[2]))
            aline = f.readline()
        f.close()
        
        #--------------------------------------------------------------------------spatial intersection and classification
        #the next line reads the depth values from the file according to cell index from above and stores the depth with the intersecting building ID
        df = pd.DataFrame(list(zip(itemgetter(*cell_index)(Z),buffer_list)), columns=['depth',str(builds_field)])
        del(Z)
        
        #based on the building ID the mean and maximum depth are established and stored in a new data frame:
        mean_depth = pd.DataFrame(df.groupby([str(builds_field)])['depth'].mean().astype(float)).round(3).reset_index(level=0).rename(columns={'depth':'mean_depth'}) 
        p90ile_depth = pd.DataFrame(df.groupby([str(builds_field)])['depth'].quantile(0.90).astype(float)).round(3).reset_index(level=0).rename(columns={'depth':'p90ile_depth'})
        damages_df = pd.merge(mean_depth, p90ile_depth)
        del(mean_depth, p90ile_depth)
        
        #calculate the damages according to the water depth in buffer zone and the type of the building
        damages_df['Class'] = 'A) Low'
        damages_df['Class'][(damages_df['mean_depth'] >= 0) & (damages_df['mean_depth'] < 0.10) & (damages_df['p90ile_depth'] < 0.30)] = 'A) Low'
        damages_df['Class'][(damages_df['mean_depth'] >= 0) & (damages_df['mean_depth'] < 0.10) & (damages_df['p90ile_depth'] >= 0.30)] = 'B) Medium'
        damages_df['Class'][(damages_df['mean_depth'] >= 0.10) & (damages_df['mean_depth'] < 0.30) & (damages_df['p90ile_depth'] < 0.30)] = 'B) Medium' 
        damages_df['Class'][(damages_df['mean_depth'] >= 0.10) & (damages_df['p90ile_depth'] >= 0.30)] = 'C) High'  
        
        #------------------------------------------------------------------------------merge results with a copy of the building layer and create output files
        builds_data = gpd.read_file(builds_file)
        builds_df = gpd.GeoDataFrame(builds_data[[str(builds_field), 'geometry']])
        finalf = builds_df.merge(damages_df, on = str(builds_field), how = 'left') #the merging of the building shapefile
        
        finalf['Area'] = (finalf.area).astype(int)#calculate the area for each building
        finalf.to_file(os.path.dirname(input_folder) + '/Exposure_Outputs/' + str(filename.split('.')[0]) + '_exposure.shp')
        class_low = (finalf['Class'] == 'A) Low').sum()
        class_medium = (finalf['Class'] == 'B) Medium').sum()        
        class_high = (finalf['Class'] == 'C) High').sum()
        del(damages_df)
        
        del(finalf['geometry'])
        finalf_csv = pd.DataFrame(finalf)
        finalf_csv.to_csv(os.path.dirname(input_folder) + '/Exposure_Outputs/' + str(filename.split('.')[0]) + '_exposure.csv')
        
        del(builds_data, builds_df, finalf, finalf_csv, df)
        
        with open(os.path.dirname(input_folder) + '/Exposure_Outputs/' + str(filename.split('.')[0]) + '_exposure_summary.txt', 'w') as sum_results:
            sum_results.write('Summary of Exposure Analysis for: ' + str(filename) + '\n\n'
                        + 'Input folder: ' + str(input_folder) + '\n'
                        + ' Buildings: ' + str(builds_file) + '\n\n'
                        + 'Number of depth files: ' + str(len(file_count)) + '\n'
                        + 'Number of Buildings: ' + str(builds_n) + '\n'
                        + 'Grid Resolution: ' + str(dx) + 'm' + '\n'
                        + 'Buffer Distance: ' + str(buffer_value) + '% or ' + str(buffer_distance) + 'm' + '\n\n'
                        + 'Low: ' + str(class_low) + '\n'
                        + 'Medium: ' + str(class_medium) + '\n'
                        + 'High: ' + str(class_high) + '\n\n')
            sum_results.close()
            
    del(x, y)
    del(buffer_list, cell_index, df_b)
    print('The Exposure Analysis is Finished. Time required: ' + str(datetime.datetime.now() - T_start)[:-4])
    
process_data('test')
